import asyncio
import tempfile
import unittest
import time
from pathlib import Path
from unittest.mock import patch

from router.workflow_domain import WorkflowDomainJournal
from router.workflow_runtime import WorkflowRuntimeService
from router.access import owner_key

PLAN={
    "plan_id":"plan_1",
    "plan_hash":"hash_1",
    "strategy":"A_EXISTING_MXD",
    "goal":{"goal_type":"build_map","dry_run":True},
    "nodes":[
        {"step_id":"s1","action":"arcmap_goal_validate","arguments":{}},
    ],
    "dry_run_nodes":["s1"],
    "blockers":[],
}
OWNER={
    "session_id":owner_key("principal-a", "workspace-a"),
    "device_id":"dev1",
    "execution_context":{"context_version":1,"principal_id":"principal-a", "workspace_id":"workspace-a", "device_id":"dev1", "deadline":time.time()+3600,"effective_resources":[{"resource_id":"installation:demo","kind":"arcmap"}]},
    "request_id":"req1",
    "trace_id":"trc1",
}

class FakeOrchestrator:
    def __init__(self):
        self.submits=[]
        self.cancelled=[]
        self.task_state="queued"
        self.cancel_ack=True

    async def submit(self,service_id,tool_name,arguments,meta):
        self.submits.append((service_id,tool_name,arguments,meta))
        return {"accepted":True,"task_id":"task_1","state":"queued"}

    async def status(self,task_id):
        return {"ok":True,"task":{"task_id":task_id,"state":self.task_state}}

    async def cancel(self,task_id):
        self.cancelled.append(task_id)
        if not self.cancel_ack:
            return {"ok":False,"task_id":task_id,"reason":"already_terminal"}
        self.task_state="cancelled"
        return {"ok":True,"task_id":task_id}

class WorkflowRuntimeTests(unittest.TestCase):
    def setUp(self):
        # Facade tests isolate scheduling/ownership from compiler validation;
        # compiler integrity is enforced by the production facade separately.
        self.compiler = patch("router.workflow_runtime.validate_compiled_plan", return_value=[])
        self.compiler.start()
        self.addCleanup(self.compiler.stop)
        self.policy = patch("router.workflow_runtime.load_tunnel_config", return_value={"workflow_policy":{"allowed_strategies":["A_EXISTING_MXD","D_CURRENT_MXD_IN_PLACE_CARTOGRAPHY","B_TEMPLATE_DATA","C_BLANK_DATA"]}})
        self.policy.start()
        self.addCleanup(self.policy.stop)
        self.tmp=tempfile.TemporaryDirectory()
        self.j=WorkflowDomainJournal(Path(self.tmp.name)/"workflow.sqlite")
        self.o=FakeOrchestrator()
        self.s=WorkflowRuntimeService(self.j,self.o,service_id="zagent_arcmap",device_id="dev1")

    def tearDown(self):
        self.j.close()
        self.tmp.cleanup()

    def arun(self,coro):
        return asyncio.run(coro)

    def test_dry_run_submit_returns_durable_run_and_task(self):
        r=self.arun(self.s.submit(plan=PLAN,owner=OWNER,idempotency_key="k",priority=2))
        self.assertTrue(r["ok"])
        self.assertEqual(r["status"],"QUEUED")
        self.assertTrue(r["run_id"].startswith("run_"))
        self.assertEqual(r["task_id"],"task_1")
        self.assertEqual(len(self.o.submits),1)
        svc,tool,args,meta=self.o.submits[0]
        self.assertEqual(svc,"zagent_arcmap")
        self.assertEqual(tool,"arcmap_goal_validate")
        self.assertEqual(args["plan"]["plan_hash"],"hash_1")
        self.assertEqual(meta["access_mode"],"write")

    def test_duplicate_does_not_reschedule(self):
        a=self.arun(self.s.submit(plan=PLAN,owner=OWNER,idempotency_key="same"))
        b=self.arun(self.s.submit(plan=PLAN,owner=OWNER,idempotency_key="same"))
        self.assertEqual(a["run_id"],b["run_id"])
        self.assertTrue(b["duplicate"])
        self.assertEqual(len(self.o.submits),1)

    def test_task_success_closes_dry_run(self):
        r=self.arun(self.s.submit(plan=PLAN,owner=OWNER,idempotency_key="success"))
        self.o.task_state="succeeded"
        s=self.arun(self.s.status(r["run_id"],OWNER["session_id"]))
        self.assertTrue(s["ok"])
        self.assertEqual(s["status"],"SUCCEEDED")
        self.assertEqual(s["freshness"]["source"],"tunnel_scheduler")
        self.assertEqual(s["freshness"]["task_id"],"task_1")
        self.assertIn("observed_at_epoch",s["freshness"])
        self.assertIn("document_revision",s["freshness"])
        report=self.j.report(r["run_id"],OWNER["session_id"])
        self.assertEqual(report["run"]["state"],"SUCCEEDED")
        self.assertTrue(any(v["status"]=="PASS" for v in report["validations"]))
        states={x["step_id"]:x["state"] for x in report["steps"]}
        self.assertEqual(states["s1"],"SUCCEEDED")

    def test_wrong_owner_status_is_denied(self):
        r=self.arun(self.s.submit(plan=PLAN,owner=OWNER,idempotency_key="owner"))
        s=self.arun(self.s.status(r["run_id"],"chat_b"))
        self.assertFalse(s["ok"])
        self.assertEqual(s["errors"][0]["code"],"ACCESS_DENIED")

    def test_summary_syncs_task_state_for_manager_read_model(self):
        r=self.arun(self.s.submit(plan=PLAN,owner=OWNER,idempotency_key="summary"))
        self.o.task_state="succeeded"
        summary=self.arun(self.s.summary(OWNER["session_id"]))
        row=next(x for x in summary["runs"] if x["run_id"]==r["run_id"])
        self.assertEqual(row["state"],"SUCCEEDED")

    def test_wrong_device_submit_is_denied(self):
        owner=dict(OWNER); owner["device_id"]="other"
        r=self.arun(self.s.submit(plan=PLAN,owner=owner,idempotency_key="device"))
        self.assertFalse(r["ok"])
        self.assertEqual(r["errors"][0]["code"],"ACCESS_DENIED")

    def test_cancel_propagates_to_tunnel_task(self):
        r=self.arun(self.s.submit(plan=PLAN,owner=OWNER,idempotency_key="cancel"))
        c=self.arun(self.s.cancel(r["run_id"],OWNER["session_id"]))
        self.assertTrue(c["ok"])
        self.assertEqual(c["status"],"CANCEL_REQUESTED")
        self.assertTrue(c["scheduler_cancel_ack"])
        self.assertEqual(self.o.cancelled,["task_1"])

    def test_cancel_race_with_already_succeeded_dry_run_closes_cancelled(self):
        r=self.arun(self.s.submit(plan=PLAN,owner=OWNER,idempotency_key="cancel-race"))
        self.o.task_state="succeeded"
        self.o.cancel_ack=False
        c=self.arun(self.s.cancel(r["run_id"],OWNER["session_id"]))
        self.assertTrue(c["ok"])
        self.assertEqual(c["status"],"CANCEL_REQUESTED")
        self.assertFalse(c["scheduler_cancel_ack"])
        s=self.arun(self.s.status(r["run_id"],OWNER["session_id"]))
        self.assertEqual(s["status"],"CANCELLED")
        report=self.j.report(r["run_id"],OWNER["session_id"])
        self.assertTrue(any(
            v["phase"]=="dry_run_cancel_race" and v["status"]=="PASS"
            for v in report["validations"]
        ))

    def test_cancel_race_reconciles_after_restart_state(self):
        r=self.arun(self.s.submit(plan=PLAN,owner=OWNER,idempotency_key="cancel-race-restart"))
        self.o.task_state="succeeded"
        self.o.cancel_ack=False
        self.arun(self.s.cancel(r["run_id"],OWNER["session_id"]))
        self.j.transition(r["run_id"],"RECONCILING",owner_session_id=OWNER["session_id"])
        s=self.arun(self.s.status(r["run_id"],OWNER["session_id"]))
        self.assertEqual(s["status"],"CANCELLED")
        report=self.j.report(r["run_id"],OWNER["session_id"])
        self.assertTrue(any(
            v["phase"]=="dry_run_cancel_race" and v["status"]=="PASS"
            for v in report["validations"]
        ))

    def test_non_dry_strategy_b_uses_tunnel_internal_scheduler(self):
        plan=dict(PLAN)
        plan["strategy"]="B_TEMPLATE_DATA"
        plan["goal"]={
            "goal_type":"build_map",
            "dry_run":False,
            "outputs":{"output_dir":"out"},
        }
        plan["plan_hash"]="hash_write_b"
        plan["plan_id"]="plan_write_b"
        r=self.arun(self.s.submit(plan=plan,owner=OWNER,idempotency_key="write-b"))
        self.assertTrue(r["ok"])
        self.assertEqual(r["status"],"QUEUED")
        self.assertEqual(len(self.o.submits),1)
        svc,tool,args,meta=self.o.submits[0]
        self.assertEqual(svc,"__workflow__")
        self.assertEqual(tool,"arcmap_orchestrator_execute")
        self.assertEqual(args["run_id"],r["run_id"])
        self.assertEqual(meta["access_mode"],"write")

    def test_non_dry_strategy_a_uses_tunnel_internal_scheduler(self):
        plan=dict(PLAN)
        plan["goal"]={
            "goal_type":"build_map",
            "dry_run":False,
            "recipe":{"operations":[
                {"action":"set_layer_visibility","params":{
                    "layer_name":"L","visible":True}}
            ]},
            "outputs":{"output_dir":"out"},
        }
        plan["plan_hash"]="hash_write_a"
        plan["plan_id"]="plan_write_a"
        r=self.arun(self.s.submit(plan=plan,owner=OWNER,idempotency_key="write-a"))
        self.assertTrue(r["ok"])
        self.assertEqual(r["status"],"QUEUED")
        self.assertEqual(len(self.o.submits),1)
        svc,tool,args,meta=self.o.submits[0]
        self.assertEqual(svc,"__workflow__")
        self.assertEqual(tool,"arcmap_orchestrator_execute")
        self.assertEqual(args["run_id"],r["run_id"])
        self.assertEqual(meta["access_mode"],"write")

if __name__=="__main__":
    unittest.main()

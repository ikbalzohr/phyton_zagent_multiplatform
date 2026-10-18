import sys
import tempfile
import unittest
from pathlib import Path

TUNNEL_ENGINE=Path(__file__).resolve().parents[4]/"tunnel"/"engine"
sys.path.insert(0,str(TUNNEL_ENGINE))
from router.workflow_domain import WorkflowDomainJournal
from orchestrator.executor.strategy_a import StrategyAExecutor

PLAN={
    "plan_id":"p","plan_hash":"h","strategy":"A_EXISTING_MXD","goal":{"goal_type":"build_map"},
    "nodes":[{"step_id":"s100","action":"orchestrator.execute_strategy_a","arguments":{}}],
    "blockers":[],"execution_step_id":"s100","required_checkpoint_coverage":["live_state"],
    "postconditions":[{"rule":"map_ok"}],
}
CTX={"device_id":"d1","instance_id":"i1","process_start_time":"t1","document_id":"m1",
     "document_epoch":"e1","document_revision":"r1"}

class FakeLive:
    def __init__(self):
        self.identity={"ok":True,**CTX}; self.apply_result={"ok":True,"changed":1}; self.calls=[]
        self.coverage=["live_state"]; self.verify={"ok":True}
    def inspect_identity(self): self.calls.append("identity"); return dict(self.identity)
    def snapshot_state(self,**kwargs):
        self.calls.append("snapshot"); return {"ok":True,"coverage":list(self.coverage),"snapshot_id":"snap1","fingerprint":"f"}
    def validate_recipe(self,recipe): self.calls.append("validate"); return {"ok":True}
    def apply_recipe(self,recipe,**kwargs): self.calls.append("apply"); return dict(self.apply_result)
    def verify_postconditions(self,postconditions,**kwargs): self.calls.append("verify"); return dict(self.verify)
    def restore_snapshot(self,checkpoint,**kwargs): self.calls.append("restore"); return {"ok":True}

class StrategyATests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.j=WorkflowDomainJournal(Path(self.tmp.name)/"db.sqlite")
        self.live=FakeLive(); self.e=StrategyAExecutor(self.j,self.live)
        self.run,_=self.j.submit_run(owner_session_id="chat",device_id="d1",operator_alias="Ikbal",
                                     plan=PLAN,idempotency_key="k",document_revision="r1")
        self.j.transition(self.run["run_id"],"PREFLIGHT",owner_session_id="chat")
        self.j.transition(self.run["run_id"],"QUEUED",owner_session_id="chat")
        self.j.transition(self.run["run_id"],"RUNNING",owner_session_id="chat")
    def tearDown(self): self.j.close(); self.tmp.cleanup()

    def test_stale_target_blocks_before_snapshot_or_write(self):
        self.live.identity["document_id"]="other"
        r=self.e.execute(self.run["run_id"],"chat",PLAN,CTX,{"operations":[]},1)
        self.assertEqual(r["errors"][0]["code"],"TARGET_STALE")
        self.assertNotIn("apply",self.live.calls)

    def test_insufficient_checkpoint_coverage_blocks_write(self):
        self.live.coverage=[]
        r=self.e.execute(self.run["run_id"],"chat",PLAN,CTX,{"operations":[]},1)
        self.assertEqual(r["errors"][0]["code"],"ROLLBACK_COVERAGE_INSUFFICIENT")
        self.assertNotIn("apply",self.live.calls)

    def test_unknown_outcome_enters_reconciling_and_never_replays(self):
        self.live.apply_result={"ok":False,"code":"BRIDGE_TIMEOUT_AFTER_CLAIM","action_may_have_completed":True}
        r=self.e.execute(self.run["run_id"],"chat",PLAN,CTX,{"operations":[1]},1)
        self.assertEqual(r["status"],"RECONCILING"); self.assertFalse(r["replay_allowed"])
        self.assertEqual(self.live.calls.count("apply"),1)
        self.assertEqual(self.j.get_run(self.run["run_id"],"chat")["state"],"RECONCILING")

    def test_success_requires_postcondition_verification(self):
        r=self.e.execute(self.run["run_id"],"chat",PLAN,CTX,{"operations":[1]},1)
        self.assertTrue(r["ok"]); self.assertEqual(r["status"],"VALIDATING")
        self.assertEqual(self.live.calls,["identity","snapshot","validate","apply","verify"])

    def test_postcondition_failure_is_not_success(self):
        self.live.verify={"ok":False,"reason":"bad"}
        r=self.e.execute(self.run["run_id"],"chat",PLAN,CTX,{"operations":[1]},1)
        self.assertFalse(r["ok"]); self.assertEqual(r["errors"][0]["code"],"POSTCONDITION_FAILED")

    def test_cancel_before_effect_prevents_apply(self):
        r=self.e.execute(self.run["run_id"],"chat",PLAN,CTX,{"operations":[1]},1,cancel_requested=lambda:True)
        self.assertEqual(r["status"],"CANCEL_REQUESTED"); self.assertNotIn("apply",self.live.calls)

    def test_late_cancel_quarantines_result_from_publish(self):
        seq=iter([False,True])
        r=self.e.execute(self.run["run_id"],"chat",PLAN,CTX,{"operations":[1]},1,cancel_requested=lambda:next(seq))
        self.assertEqual(r["status"],"CANCEL_REQUESTED"); self.assertFalse(r["publish_allowed"])

if __name__=="__main__": unittest.main()

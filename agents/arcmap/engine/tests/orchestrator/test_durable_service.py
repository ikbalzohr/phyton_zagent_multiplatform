import copy
import sys
import tempfile
import unittest
from pathlib import Path

TUNNEL_ENGINE=Path(__file__).resolve().parents[4]/"tunnel"/"engine"
sys.path.insert(0,str(TUNNEL_ENGINE))
from router.workflow_domain import WorkflowDomainJournal
from orchestrator.executor import DurableRunService

PLAN={"plan_id":"plan_x","plan_hash":"hash_x","strategy":"A_EXISTING_MXD",
      "goal":{"goal_type":"build_map"},"nodes":[{"step_id":"s1","action":"a","arguments":{}}],"blockers":[]}
OWNER={"session_id":"chat_a","device_id":"dev1","operator_alias":"Ikbal","request_id":"r","trace_id":"t"}

class FakeScheduler:
    def __init__(self,fail=False): self.fail=fail; self.submits=[]; self.cancels=[]
    def submit(self,**kwargs):
        if self.fail: raise RuntimeError("scheduler down")
        self.submits.append(kwargs); return "task_1"
    def cancel(self,task_id,owner_session_id):
        self.cancels.append((task_id,owner_session_id)); return True

class DurableRunServiceTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.j=WorkflowDomainJournal(Path(self.tmp.name)/"db.sqlite")
        self.s=FakeScheduler(); self.r=DurableRunService(self.j,self.s)
    def tearDown(self): self.j.close(); self.tmp.cleanup()
    def test_submit_returns_run_and_task_immediately(self):
        r=self.r.submit(copy.deepcopy(PLAN),dict(OWNER),idempotency_key="k")
        self.assertTrue(r["ok"]); self.assertEqual(r["status"],"QUEUED"); self.assertEqual(r["task_id"],"task_1")
    def test_duplicate_submit_does_not_reschedule(self):
        a=self.r.submit(copy.deepcopy(PLAN),dict(OWNER),idempotency_key="k")
        b=self.r.submit(copy.deepcopy(PLAN),dict(OWNER),idempotency_key="k")
        self.assertEqual(a["run_id"],b["run_id"]); self.assertTrue(b["duplicate"]); self.assertEqual(len(self.s.submits),1)
    def test_wrong_owner_status_is_denied(self):
        r=self.r.submit(copy.deepcopy(PLAN),dict(OWNER)); s=self.r.status(r["run_id"],"chat_b")
        self.assertFalse(s["ok"]); self.assertEqual(s["errors"][0]["code"],"ACCESS_DENIED")
    def test_scheduler_failure_marks_recovery_required(self):
        service=DurableRunService(self.j,FakeScheduler(fail=True))
        r=service.submit(copy.deepcopy(PLAN),dict(OWNER),idempotency_key="fail")
        self.assertEqual(r["status"],"RECOVERY_REQUIRED")
        self.assertEqual(self.j.get_run(r["run_id"],"chat_a")["state"],"RECOVERY_REQUIRED")
    def test_cancel_requests_scheduler_but_not_immediate_cancelled(self):
        r=self.r.submit(copy.deepcopy(PLAN),dict(OWNER)); c=self.r.cancel(r["run_id"],"chat_a")
        self.assertEqual(c["status"],"CANCEL_REQUESTED"); self.assertTrue(c["scheduler_cancel_ack"])
    def test_resume_reconciling_is_fail_closed(self):
        r=self.r.submit(copy.deepcopy(PLAN),dict(OWNER))
        self.j.transition(r["run_id"],"RUNNING",owner_session_id="chat_a",expected={"QUEUED"})
        self.j.transition(r["run_id"],"RECONCILING",owner_session_id="chat_a")
        x=self.r.resume(r["run_id"],"chat_a",{"decision":"continue"})
        self.assertFalse(x["ok"]); self.assertEqual(x["errors"][0]["code"],"OUTCOME_UNKNOWN")

if __name__=="__main__": unittest.main()

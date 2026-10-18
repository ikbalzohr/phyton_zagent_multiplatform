import tempfile
import unittest
from pathlib import Path

from router.workflow_domain import WorkflowDomainJournal

PLAN={
    "plan_id":"plan_fixture","plan_hash":"hash_fixture","strategy":"A_EXISTING_MXD",
    "goal":{"goal_type":"build_map"},"nodes":[
        {"step_id":"s1","action":"read","arguments":{}},
        {"step_id":"s2","action":"write","arguments":{"x":1}}],
    "blockers":[],
}

class WorkflowDomainTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.db=Path(self.tmp.name)/"tasks.db"
        self.j=WorkflowDomainJournal(self.db)
    def tearDown(self):
        self.j.close(); self.tmp.cleanup()
    def submit(self,key="k1",plan=None,owner="chat_a"):
        return self.j.submit_run(owner_session_id=owner,device_id="dev1",operator_alias="",
            plan=plan or PLAN,idempotency_key=key)
    def test_schema_contains_required_domain_tables(self):
        names={r[0] for r in self.j.conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        self.assertTrue({"workflow_runs","workflow_plans","workflow_steps","operation_receipts","checkpoints",
                         "validations","artifacts","publish_attempts","workflow_leases","workflow_fences"} <= names)
    def test_duplicate_same_input_returns_existing(self):
        a,ca=self.submit(); b,cb=self.submit()
        self.assertTrue(ca); self.assertFalse(cb); self.assertEqual(a["run_id"],b["run_id"])
    def test_same_idempotency_different_input_conflicts(self):
        self.submit(); p=dict(PLAN); p["plan_hash"]="other"
        with self.assertRaisesRegex(ValueError,"IDEMPOTENCY_CONFLICT"): self.submit(plan=p)
    def test_wrong_owner_is_rejected(self):
        run,_=self.submit()
        with self.assertRaisesRegex(PermissionError,"WRONG_OWNER"): self.j.get_run(run["run_id"],"chat_b")
    def test_transition_state_machine_rejects_skip(self):
        run,_=self.submit()
        with self.assertRaisesRegex(ValueError,"INVALID_STATE_TRANSITION"):
            self.j.transition(run["run_id"],"SUCCEEDED",owner_session_id="chat_a")
    def test_cancel_is_durable(self):
        run,_=self.submit()
        self.j.transition(run["run_id"],"PREFLIGHT",owner_session_id="chat_a")
        row=self.j.request_cancel(run["run_id"],"chat_a")
        self.assertEqual(row["state"],"CANCEL_REQUESTED")
        reopened=WorkflowDomainJournal(self.db)
        try: self.assertEqual(reopened.get_run(run["run_id"],"chat_a")["state"],"CANCEL_REQUESTED")
        finally: reopened.close()
    def test_expired_lease_does_not_allow_automatic_takeover(self):
        a,_=self.submit("a"); b,_=self.submit("b",owner="chat_b")
        self.j.acquire_lease("arcmap:current",a["run_id"],"chat_a",ttl_seconds=-1)
        with self.assertRaisesRegex(RuntimeError,"LOCK_CONFLICT"):
            self.j.acquire_lease("arcmap:current",b["run_id"],"chat_b")
    def test_fencing_epoch_increases_after_explicit_release(self):
        a,_=self.submit("a"); b,_=self.submit("b",owner="chat_b")
        x=self.j.acquire_lease("r",a["run_id"],"chat_a")
        self.j.release_lease("r",a["run_id"],"chat_a")
        y=self.j.acquire_lease("r",b["run_id"],"chat_b")
        self.assertGreater(y["fencing_epoch"],x["fencing_epoch"])
    def test_receipt_ack_is_durable(self):
        run,_=self.submit()
        rid=self.j.record_receipt(run_id=run["run_id"],step_id="s2",request_id="req1",
                                  effect_class="live_write",outcome="SUCCEEDED",result={"ok":True})
        self.j.acknowledge_receipt(rid)
        self.assertEqual(self.j.report(run["run_id"],"chat_a")["receipts"][0]["acknowledged"],1)

if __name__=="__main__": unittest.main()

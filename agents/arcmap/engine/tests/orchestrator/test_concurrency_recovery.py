import sys
import tempfile
import unittest
from pathlib import Path

TUNNEL_ENGINE=Path(__file__).resolve().parents[4]/"tunnel"/"engine"
sys.path.insert(0,str(TUNNEL_ENGINE))
from router.workflow_domain import WorkflowDomainJournal

from orchestrator.concurrency import (
    ResourceClaim, arcmap_document_key, path_resource_key, claims_conflict,
    stable_claim_order, conflict_matrix, UpdateDrainController,
)
from orchestrator.executor.reconciliation import reconcile_outcome, late_result_policy

PLAN={"plan_id":"p","plan_hash":"h","strategy":"A_EXISTING_MXD",
      "goal":{},"nodes":[{"step_id":"s","action":"a","arguments":{}}],"blockers":[]}

class ConcurrencyTests(unittest.TestCase):
    def test_arcmap_key_requires_full_instance_identity(self):
        with self.assertRaisesRegex(ValueError,"INCOMPLETE_ARCMAP_IDENTITY"):
            arcmap_document_key("d","i","t","m","")
        k=arcmap_document_key("d","i","t","m","e")
        self.assertEqual(k,"arcmap:d:i:t:m:e")

    def test_path_key_normalizes_case_and_separators(self):
        a=path_resource_key(r"C:\Data\A\..\Map.pdf","output")
        b=path_resource_key(r"c:\data\map.pdf","output")
        self.assertEqual(a,b)

    def test_same_resource_two_writers_conflict(self):
        a=ResourceClaim("r","write","chat_a"); b=ResourceClaim("r","write","chat_b")
        self.assertTrue(claims_conflict(a,b))
        self.assertEqual(len(conflict_matrix([a,b])),1)

    def test_readers_do_not_conflict(self):
        self.assertFalse(claims_conflict(ResourceClaim("r","read"),ResourceClaim("r","read")))

    def test_stable_order_is_deterministic(self):
        claims=[ResourceClaim("z","write","b"),ResourceClaim("a","write","a"),ResourceClaim("a","read","c")]
        self.assertEqual(stable_claim_order(claims),stable_claim_order(list(reversed(claims))))
        self.assertEqual(stable_claim_order(claims)[0].mode,"read")

    def test_update_drain_preserves_files_and_blocks_new_arcmap_write(self):
        d=UpdateDrainController(); d.begin("upgrade")
        self.assertTrue(d.can_submit("zagent_files","write"))
        self.assertTrue(d.can_submit("zagent_arcmap","read"))
        self.assertFalse(d.can_submit("zagent_arcmap","live_write"))
        self.assertFalse(d.safe_to_restart("zagent_files"))

    def test_active_arcmap_write_blocks_restart_until_complete(self):
        d=UpdateDrainController(); d.register_active("t","zagent_arcmap","live_write"); d.begin()
        self.assertFalse(d.safe_to_restart("zagent_arcmap"))
        d.complete("t"); self.assertTrue(d.safe_to_restart("zagent_arcmap"))

class ReconciliationTests(unittest.TestCase):
    def test_unknown_write_never_auto_retries(self):
        r=reconcile_outcome(effect_class="live_write",receipt={"outcome":"OUTCOME_UNKNOWN"})
        self.assertEqual(r["status"],"RECOVERY_REQUIRED"); self.assertFalse(r["retry_allowed"])

    def test_never_claimed_is_safe_to_retry(self):
        r=reconcile_outcome(effect_class="live_write",receipt={"effect_applied":False},worker_state={"claimed":False})
        self.assertEqual(r["status"],"SAFE_TO_RETRY"); self.assertTrue(r["retry_allowed"])

    def test_verified_export_artifact_reconciles_success(self):
        r=reconcile_outcome(effect_class="export",receipt={"outcome":"OUTCOME_UNKNOWN"},artifact={"verified":True})
        self.assertEqual(r["status"],"SUCCEEDED"); self.assertFalse(r["retry_allowed"])

    def test_late_result_after_cancel_never_publishes(self):
        r=late_result_policy(True,{"ok":True})
        self.assertFalse(r["publish_allowed"]); self.assertEqual(r["state"],"CANCEL_REQUESTED")

class RestartRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.db=Path(self.tmp.name)/"d.sqlite"
        self.j=WorkflowDomainJournal(self.db)
    def tearDown(self):
        self.j.close(); self.tmp.cleanup()
    def submit(self,key,owner):
        return self.j.submit_run(owner_session_id=owner,device_id="dev",operator_alias="Ikbal",plan=PLAN,idempotency_key=key)[0]
    def test_restart_recovery_keeps_queued_but_reconciles_running(self):
        a=self.submit("a","chat_a"); b=self.submit("b","chat_b")
        for run,owner in ((a,"chat_a"),(b,"chat_b")):
            self.j.transition(run["run_id"],"PREFLIGHT",owner_session_id=owner)
            self.j.transition(run["run_id"],"QUEUED",owner_session_id=owner)
        self.j.transition(a["run_id"],"RUNNING",owner_session_id="chat_a")
        recovered=self.j.recover_incomplete_runs()
        self.assertIn(a["run_id"],recovered); self.assertNotIn(b["run_id"],recovered)
        self.assertEqual(self.j.get_run(a["run_id"],"chat_a")["state"],"RECONCILING")
        self.assertEqual(self.j.get_run(b["run_id"],"chat_b")["state"],"QUEUED")
    def test_owner_listing_never_leaks_other_session(self):
        a=self.submit("a","chat_a"); self.submit("b","chat_b")
        rows=self.j.list_runs("chat_a")
        self.assertEqual([x["run_id"] for x in rows],[a["run_id"]])

if __name__=="__main__": unittest.main()

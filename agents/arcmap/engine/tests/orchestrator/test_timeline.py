import unittest

from orchestrator.reporting import build_timeline, evidence_view

class TimelineTests(unittest.TestCase):
    def test_progress_uses_known_steps_not_fake_eta(self):
        run={"run_id":"r","state":"RUNNING","task_id":"t","cancel_requested":0}
        steps=[{"step_id":"a","state":"SUCCEEDED"},{"step_id":"b","state":"RUNNING"},{"step_id":"c","state":"PENDING"}]
        t=build_timeline(run,steps)
        self.assertEqual(t["completed_steps"],1); self.assertEqual(t["total_steps"],3)
        self.assertAlmostEqual(t["progress"],1/3); self.assertIsNone(t["eta_seconds"])
        self.assertFalse(t["eta_is_evidence_based"])

    def test_eta_only_when_evidence_is_supplied(self):
        t=build_timeline({"state":"RUNNING"},[],history_eta=12.5)
        self.assertEqual(t["eta_seconds"],12.5); self.assertTrue(t["eta_is_evidence_based"])

    def test_waiting_reason_surfaces_blocker(self):
        run={"run_id":"r","state":"BLOCKED","blockers":[{"code":"LICENSE_UNAVAILABLE"}]}
        t=build_timeline(run,[])
        self.assertEqual(t["waiting_reason"],"LICENSE_UNAVAILABLE")

    def test_cancel_state_is_explicit(self):
        t=build_timeline({"state":"CANCEL_REQUESTED","cancel_requested":1},[])
        self.assertTrue(t["cancel_requested"]); self.assertEqual(t["state"],"CANCEL_REQUESTED")

    def test_artifact_summary_does_not_call_partial_output_valid(self):
        t=build_timeline({"state":"PUBLISHING"},[],artifacts=[{"valid":True},{"valid":False}])
        self.assertEqual(t["artifact_summary"]["valid"],1); self.assertFalse(t["artifact_summary"]["all_valid"])

    def test_evidence_view_only_uses_given_run_evidence(self):
        report={"run":{"run_id":"r"},"validations":[{"id":"v"}],"artifacts":[{"id":"a"}],
                "receipts":[{"id":"x"}],"publish_attempts":[{"id":"p"}]}
        e=evidence_view(report)
        self.assertEqual(e["run_id"],"r"); self.assertEqual(len(e["publish_attempts"]),1)

if __name__=="__main__": unittest.main()

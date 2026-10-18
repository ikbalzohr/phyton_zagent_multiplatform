"""Artifact authorization/range/integrity regression source. NOT_RUN."""
import base64
import hashlib
import tempfile
import unittest
from pathlib import Path

from router.access import owner_key
from router.artifacts import read_artifact
from router.workflow_domain import WorkflowDomainJournal


class ArtifactSecurityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.journal = WorkflowDomainJournal(self.root / "workflow.db")
        self.owner = owner_key("principal-a", "ws")
        self.run_id, _ = self.journal.submit_run(
            owner_session_id=self.owner, device_id="device", operator_alias="",
            plan={"plan_id": "p", "plan_hash": "h", "goal": {}, "nodes": []},
            idempotency_key="k")
        self.content = b"%PDF-1.7\nsynthetic fixture only"
        self.path = self.root / "result.pdf"
        self.path.write_bytes(self.content)
        self.artifact = self.journal.add_artifact(
            str(self.run_id["run_id"]), "PDF", "FINAL", str(self.path),
            hashlib.sha256(self.content).hexdigest(), True)

    def tearDown(self):
        self.journal.close()
        self.tmp.cleanup()

    def test_bounded_verified_bytes_not_windows_path(self):
        result = read_artifact(self.journal, self.artifact, self.owner, [str(self.root)], 0, 8)
        self.assertEqual(base64.b64decode(result["content"]), self.content[:8])
        self.assertEqual(result["mime_type"], "application/pdf")
        self.assertNotIn("path", result)
        self.assertFalse(result["eof"])

    def test_other_principal_cannot_enumerate_artifact(self):
        with self.assertRaises(KeyError):
            read_artifact(self.journal, self.artifact, owner_key("other", "ws"), [str(self.root)])

    def test_mutated_artifact_is_not_delivered(self):
        self.path.write_bytes(b"tampered")
        with self.assertRaisesRegex(ValueError, "HASH_MISMATCH"):
            read_artifact(self.journal, self.artifact, self.owner, [str(self.root)])

    def test_unprovisioned_root_and_excessive_range_denied(self):
        with self.assertRaises(PermissionError):
            read_artifact(self.journal, self.artifact, self.owner, [])
        with self.assertRaises(ValueError):
            read_artifact(self.journal, self.artifact, self.owner, [str(self.root)], 0, 262145)


if __name__ == "__main__":
    unittest.main()

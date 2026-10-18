"""No-blind-replay and neutral ownership journal regression source. NOT_RUN."""
import tempfile
import unittest
from pathlib import Path

from router.access import owner_key
from router.orchestration import Orchestrator, TaskJournal


class RecoveryTests(unittest.IsolatedAsyncioTestCase):
    async def test_restart_quarantines_uncertain_and_queued_tasks(self):
        with tempfile.TemporaryDirectory() as root:
            journal = TaskJournal(Path(root) / "tasks.db")
            for state in ("queued", "running", "cancelling"):
                await journal.create({
                    "task_id": state, "session_id": owner_key("p", "w"),
                    "request_id": "r", "trace_id": "tr", "service_id": "files",
                    "tool_name": "write", "arguments_json": "{}",
                    "resource_key": "installation:a", "access_mode": "write",
                    "priority": 2, "state": state, "created_at": 1, "updated_at": 1})
            self.assertEqual(await journal.recover_incomplete(), [])
            for row in await journal.list():
                self.assertEqual(row["state"], "orphaned")
                self.assertEqual(row["error"], "RECOVERY_REQUIRED")
            journal.conn.close()

    async def test_public_job_uses_neutral_ownership_not_legacy_binding(self):
        with tempfile.TemporaryDirectory() as root:
            async def executor(*_args):
                return {"ok": True}
            orchestrator = Orchestrator(executor, Path(root) / "tasks.db")
            context = {"principal_id": "p", "workspace_id": "w", "operation_id": "op"}
            receipt = await orchestrator.submit("files", "stat", {}, {
                "session_id": owner_key("p", "w"), "execution_context": context})
            public = (await orchestrator.status(receipt["task_id"]))["task"]
            self.assertEqual(public["principal_id"], "p")
            self.assertEqual(public["workspace_id"], "w")
            self.assertNotIn("operator_alias", public)
            self.assertNotIn("execution_context_json", public)
            orchestrator.journal.conn.close()


if __name__ == "__main__":
    unittest.main()

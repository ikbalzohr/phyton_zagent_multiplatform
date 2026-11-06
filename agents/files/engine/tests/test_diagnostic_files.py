"""Files MCP diagnostic boundary tests, always isolated from a live installation.

A Files test runner may inherit ZAGENT_FILES_* environment variables pointing
at the running owner's service. Each test uses its own Python process, so
app.paths and the engine journal are initialized only inside a disposable root.
"""
from __future__ import annotations

import importlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ENGINE_ROOT = Path(__file__).resolve().parents[1]
CHILD = os.environ.get("ZAGENT_DIAGNOSTIC_CHILD") == "1"
sys.path.insert(0, str(ENGINE_ROOT))


if CHILD:
    class FilesDiagnosticRuntimeTests(unittest.IsolatedAsyncioTestCase):
        @classmethod
        def setUpClass(cls):
            cls.root = Path(os.environ["ZAGENT_DIAGNOSTIC_ROOT"])
            from app.paths import CONFIG_DIR, RUNTIME_DIR
            if CONFIG_DIR != cls.root / "config" or RUNTIME_DIR != cls.root / "runtime":
                raise RuntimeError("DIAGNOSTIC_TEST_ROOT_NOT_ISOLATED")
            cls.server = importlib.import_module("app.mcp.server")

        @classmethod
        def tearDownClass(cls):
            # Release both the SQLite connection and the exclusive Windows lock
            # before the parent deletes its temporary workspace.
            cls.server.engine.pool.shutdown(wait=True, cancel_futures=True)
            cls.server.engine.journal.close()

        async def test_tool_boundary_returns_sanitized_correlated_mcp_error(self):
            from mcp.types import CallToolRequest, CallToolRequestParams
            secret = "Bearer raw-token /private/config owner-secret"
            handler = self.server.mcp._mcp_server.request_handlers[CallToolRequest]
            with patch.object(self.server, "request_meta", side_effect=PermissionError(secret)):
                result = await handler(CallToolRequest(
                    method="tools/call",
                    params=CallToolRequestParams(name="files_ping", arguments={})))
            body = result.root.model_dump(mode="json", exclude_none=True)
            self.assertTrue(body["isError"])
            self.assertNotIn(secret, json.dumps(body))
            correlation = body["structuredContent"]["error"]["data"]["requestId"]
            self.assertRegex(correlation, r"^[a-f0-9]{32}$")
            events_path = self.root / "private/logs/diagnostics/files.jsonl"
            events = [json.loads(line) for line in events_path.read_text(encoding="utf-8").splitlines()]
            self.assertTrue(any(e["requestId"] == correlation
                                and e["stage"] == "files.authentication" for e in events))
            self.assertNotIn(secret, json.dumps(events))

        async def test_operation_failure_journal_and_diagnostics_never_copy_exception_text(self):
            import threading
            engine = self.server.engine
            secret = "Bearer raw-operation-token /private/operation/path"
            meta = {}
            operation_id, _ = engine.journal.claim(
                "ping", "fixture-owner", "fixture-idem", "fingerprint", meta)
            meta["operation_id"] = operation_id
            with patch.object(engine.locks, "acquire", side_effect=RuntimeError(secret)):
                with self.assertRaises(RuntimeError):
                    await engine._run_with_catalog(
                        "ping", {}, meta, {"name": "fixture"}, [], threading.Event())
            row = engine.journal.get(operation_id, "fixture-owner")
            self.assertEqual(row["state"], "failed")
            self.assertNotIn(secret, json.dumps(row))
            events_path = self.root / "private/logs/diagnostics/files.jsonl"
            events = [json.loads(line) for line in events_path.read_text(encoding="utf-8").splitlines()]
            self.assertTrue(any(e["stage"] == "files.operation" for e in events))


else:
    class FilesDiagnosticTests(unittest.TestCase):
        def _run_isolated(self, method):
            with tempfile.TemporaryDirectory(prefix="zagent-files-diag-") as directory:
                root = Path(directory)
                config = root / "config"
                config.mkdir()
                (config / "settings.json").write_text(json.dumps({
                    "host": "127.0.0.1", "port": 8011, "secret_names": [".env"]
                }), encoding="utf-8")
                (config / "profiles.json").write_text(json.dumps({
                    "schema_version": "2.0",
                    "active_profile": "agentRoot",
                    "profiles": []
                }), encoding="utf-8")
                env = dict(os.environ)
                # Drop inherited service paths before specifying a complete,
                # disposable local store. Never reuse the live service journal.
                for key in tuple(env):
                    if key.startswith("ZAGENT_FILES_") or key in (
                        "ZAGENT_CORE_DATA_ROOT", "ZAGENT_INTERNAL_TOKEN",
                        "ZAGENT_DIAGNOSTIC_ROOT", "ZAGENT_DIAGNOSTIC_CHILD"):
                        env.pop(key)
                env.update({
                    "ZAGENT_DIAGNOSTIC_CHILD": "1",
                    "ZAGENT_DIAGNOSTIC_ROOT": str(root),
                    "ZAGENT_FILES_ENGINE_ROOT": str(ENGINE_ROOT),
                    "ZAGENT_FILES_DATA_ROOT": str(root),
                    "ZAGENT_FILES_CONFIG_DIR": str(config),
                    "ZAGENT_FILES_RUNTIME_DIR": str(root / "runtime"),
                    "ZAGENT_FILES_LOG_DIR": str(root / "logs"),
                    "ZAGENT_FILES_BACKUP_ROOT": str(root / "runtime/backups"),
                    "ZAGENT_FILES_UPDATE_STATE_ROOT": str(root / "updates"),
                    "ZAGENT_CORE_DATA_ROOT": str(root / "private"),
                })
                result = subprocess.run(
                    [sys.executable, str(Path(__file__).resolve()), method],
                    cwd=ENGINE_ROOT, env=env, text=True, capture_output=True,
                    timeout=45, check=False)
                self.assertEqual(
                    result.returncode, 0,
                    f"Isolated diagnostic test {method} failed.\n"
                    f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}")

        def test_tool_boundary_returns_sanitized_correlated_mcp_error(self):
            self._run_isolated("test_tool_boundary_returns_sanitized_correlated_mcp_error")

        def test_operation_failure_journal_and_diagnostics_never_copy_exception_text(self):
            self._run_isolated("test_operation_failure_journal_and_diagnostics_never_copy_exception_text")


if __name__ == "__main__":
    if CHILD:
        case = sys.argv[1] if len(sys.argv) > 1 else ""
        tests = unittest.defaultTestLoader.loadTestsFromName(
            "FilesDiagnosticRuntimeTests." + case, module=sys.modules[__name__])
        outcome = unittest.TextTestRunner(verbosity=1).run(tests)
        sys.exit(0 if outcome.wasSuccessful() else 1)
    unittest.main()

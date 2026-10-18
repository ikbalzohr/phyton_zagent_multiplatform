import json
import tempfile
import threading
import time
import unittest
from pathlib import Path

from mcp_server.ipc_client import send_command_via
import mcp_server.services as services_module


class UpstreamProxyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.data = self.root / "data"
        self.ipc = self.data / "ipc"
        (self.data / "runtime").mkdir(parents=True)
        (self.ipc / "inbox").mkdir(parents=True)
        (self.ipc / "outbox").mkdir(parents=True)
        (self.ipc / "archive").mkdir(parents=True)
        owner = {
            "running": True,
            "updated_at_epoch": time.time(),
            "context": {"document_id": "doc1"},
        }
        (self.data / "runtime" / "arcmap-owner.json").write_text(
            json.dumps(owner), encoding="utf-8"
        )

    def tearDown(self):
        self.tmp.cleanup()

    def _serve_once(self, result=None):
        result = result or {"ok": True}
        deadline = time.time() + 2
        while time.time() < deadline:
            files = list((self.ipc / "inbox").glob("*.json"))
            if files:
                path = files[0]
                command = json.loads(path.read_text(encoding="utf-8"))
                request_id = command["request_id"]
                payload = dict(result)
                payload["request_id"] = request_id
                (self.ipc / "outbox" / (request_id + ".json")).write_text(
                    json.dumps(payload), encoding="utf-8"
                )
                path.unlink(missing_ok=True)
                return
            time.sleep(0.01)
        raise RuntimeError("test bridge did not receive request")

    def test_send_command_via_uses_external_owner_and_queue(self):
        thread = threading.Thread(
            target=self._serve_once,
            kwargs={"result": {"ok": True, "source": "production"}},
        )
        thread.start()
        result = send_command_via(
            self.ipc, self.data, "ping", timeout=1
        )
        thread.join(timeout=2)
        self.assertTrue(result["ok"])
        self.assertEqual(result["source"], "production")

    def test_dev_upstream_blocks_write_before_queueing(self):
        old = (
            services_module._UPSTREAM_READ_ONLY,
            services_module._UPSTREAM_IPC_ROOT,
            services_module._UPSTREAM_DATA_ROOT,
        )
        try:
            services_module._UPSTREAM_READ_ONLY = True
            services_module._UPSTREAM_IPC_ROOT = str(self.ipc)
            services_module._UPSTREAM_DATA_ROOT = str(self.data)
            service = services_module.AgentServices()
            result = service.call(
                "set_title",
                kind="live_write",
                title="blocked",
            )
            self.assertFalse(result["ok"])
            self.assertEqual(
                result["code"], "DEV_UPSTREAM_READ_ONLY"
            )
            self.assertEqual(
                list((self.ipc / "inbox").glob("*.json")), []
            )
        finally:
            (
                services_module._UPSTREAM_READ_ONLY,
                services_module._UPSTREAM_IPC_ROOT,
                services_module._UPSTREAM_DATA_ROOT,
            ) = old

    def test_bridge_owner_status_reports_upstream_mode(self):
        old = (
            services_module._UPSTREAM_READ_ONLY,
            services_module._UPSTREAM_IPC_ROOT,
            services_module._UPSTREAM_DATA_ROOT,
        )
        try:
            services_module._UPSTREAM_READ_ONLY = True
            services_module._UPSTREAM_IPC_ROOT = str(self.ipc)
            services_module._UPSTREAM_DATA_ROOT = str(self.data)
            status = services_module.AgentServices().bridge_owner_status()
            self.assertTrue(status["healthy"])
            self.assertEqual(
                status["bridge_mode"], "UPSTREAM_READ_ONLY"
            )
        finally:
            (
                services_module._UPSTREAM_READ_ONLY,
                services_module._UPSTREAM_IPC_ROOT,
                services_module._UPSTREAM_DATA_ROOT,
            ) = old


if __name__ == "__main__":
    unittest.main()

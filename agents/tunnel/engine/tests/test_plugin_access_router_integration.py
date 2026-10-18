"""ASGI perimeter tests with synthetic introspection, no sockets. NOT_RUN."""
import importlib
import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch
import httpx
from router.access import principal_id

class RouterPerimeterTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        runtime = root/"runtime"; runtime.mkdir()
        resource = {"resource_uri":"https://resource.example/mcp", "issuer":"https://issuer.example",
            "authorization_servers":["https://issuer.example"], "introspection_endpoint":"https://issuer.example/introspect",
            "introspection_client_id":"resource", "introspection_secret_env":"TEST_AS_SECRET", "workspace_id":"ws", "policy_revision":"1",
            "grants":{principal_id("https://issuer.example","alice"):{"scopes":["zagent:read"],"tools":[]}}}
        (root/"tunnel.json").write_text(json.dumps({"router":{},"resource_server":resource,"tool_policy":{}}))
        for name in ("core_services", "additional_services"):
            (root/(name+".json")).write_text('{"services":[]}')
        import router.config as config
        import router.orchestration as orchestration
        self.patches = [patch.object(config,"TUNNEL_FILE",root/"tunnel.json"),
            patch.object(config,"CORE_FILE",root/"core_services.json"),
            patch.object(config,"ADDITIONAL_FILE",root/"additional_services.json"),
            patch.object(orchestration,"DB_PATH",runtime/"tasks.db"),
            patch.dict(os.environ,{"ZAGENT_TUNNEL_RUNTIME_DIR":str(runtime),"ZAGENT_DEVICE_ID":"device","ZAGENT_INSTALLATION_ID":"install","TEST_AS_SECRET":"synthetic-only"})]
        for p in self.patches: p.start()
        import sys
        self.server = importlib.reload(sys.modules["router.server"]) if "router.server" in sys.modules else importlib.import_module("router.server")
        async def introspection(request):
            return httpx.Response(200,json={"active":True,"iss":"https://issuer.example","sub":"alice","aud":"https://resource.example/mcp","scope":"zagent:read","exp":time.time()+300})
        self.server._auth_client = httpx.AsyncClient(transport=httpx.MockTransport(introspection))
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=self.server.app),base_url="http://127.0.0.1")

    async def asyncTearDown(self):
        await self.client.aclose()
        await self.server._auth_client.aclose()
        self.server._auth_client = None
        self.server.orchestrator.journal.conn.close()
        self.server.workflow_journal.close()
        for p in reversed(self.patches): p.stop()
        self.tmp.cleanup()

    async def test_missing_bearer_rejected_before_initialize(self):
        response = await self.client.post("/mcp",json={"jsonrpc":"2.0","id":1,"method":"initialize"})
        self.assertEqual(response.status_code,401)
        self.assertIn("resource_metadata", response.headers["www-authenticate"])

    async def test_client_labels_and_transport_session_do_not_change_principal(self):
        for label in ("arbitrary", "Claude", "Codex", "ChatGPT", "Hermes"):
            response = await self.client.post("/mcp", headers={"Authorization":"Bearer synthetic", "User-Agent":label,"Mcp-Session-Id":"untrusted"},
                json={"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"zagent_access_status","arguments":{},"_meta":{"openai/session":"forged","principal_id":"administrator"}}})
            self.assertEqual(response.status_code,200)
            value = json.loads(response.json()["result"]["content"][0]["text"])
            self.assertEqual(value["principal_id"],principal_id("https://issuer.example","alice"))
            self.assertNotIn("mcp-session-id",response.headers)

    async def test_control_plane_is_not_public_even_with_resource_bearer(self):
        response = await self.client.get("/router/status",headers={"Authorization":"Bearer synthetic"})
        self.assertIn(response.status_code,(403,503))

    async def test_disallowed_origin_rejected(self):
        response = await self.client.post("/mcp",headers={"Authorization":"Bearer synthetic","Origin":"https://evil.example"},json={})
        self.assertEqual(response.status_code,403)

    async def test_modern_protocol_not_falsely_advertised(self):
        response = await self.client.post("/mcp",headers={"Authorization":"Bearer synthetic"},
            json={"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-11-25"}})
        result = response.json()["result"]
        self.assertEqual(result["serverInfo"]["version"],"1.0.0")
        self.assertEqual(result["capabilities"]["tools"],{})
        self.assertNotIn("mcp-session-id",response.headers)

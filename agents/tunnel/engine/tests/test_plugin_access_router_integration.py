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

    async def test_opt_in_all_discovered_exposes_only_granted_known_agents(self):
        from router.registry import UpstreamState
        import router.config as config

        path = config.TUNNEL_FILE
        original = json.loads(path.read_text(encoding="utf-8"))
        principal = principal_id("https://issuer.example", "alice")
        original["catalog_exposure"] = {"mode": "all_discovered"}
        original["resource_server"]["grants"][principal] = {
            "scopes": ["files:read", "files:write", "files:execute", "web:control", "arcmap:execute"],
            "tools": ["*"],
            "files_resource": {"kind": "files", "profile_id": "appBridge",
                "resource_id": "workspace:ws:approved", "device_id": "device",
                "installation_id": "install", "revoked": False},
        }
        path.write_text(json.dumps(original), encoding="utf-8")
        async def full_introspection(request):
            return httpx.Response(200, json={
                "active": True, "iss": "https://issuer.example", "sub": "alice",
                "aud": "https://resource.example/mcp",
                "scope": "files:read files:write files:execute web:control arcmap:execute",
                "exp": time.time() + 300})
        await self.server._auth_client.aclose()
        self.server._auth_client = httpx.AsyncClient(transport=httpx.MockTransport(full_introspection))
        catalog = {
            "zagent_files": ("files", ["files_list", "files_write", "files_powershell_run",
                                      "files_update_apply"]),
            "zagent_web": ("web", ["web_snapshot"]),
            "zagent_arcmap": ("arcmap", ["arcmap_status"]),
            "zagent_qgis": ("qgis", ["qgis_project_info"]),
        }
        self.server.registry.states = {}
        for service_id, (namespace, names) in catalog.items():
            state = UpstreamState(service={"id": service_id, "name": service_id,
                "namespace": namespace, "url": "http://127.0.0.3:10000/mcp",
                "enabled": True, "internal_auth": service_id != "zagent_qgis"})
            state.tools = [{"name": name, "description": name,
                            "inputSchema": {"type": "object", "properties": {}}}
                           for name in names]
            self.server.registry.states[service_id] = state
        self.server.registry.rebuild_index()
        async def listing():
            response = await self.client.post("/mcp",
                headers={"Authorization": "Bearer synthetic"},
                json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
            self.assertEqual(response.status_code, 200)
            return {row["name"] for row in response.json()["result"]["tools"]}
        names = await listing()
        for expected in ("files_list", "files_write", "files_powershell_run",
                         "web_snapshot", "arcmap_status", "qgis_project_info"):
            self.assertIn(expected, names)
        self.assertNotIn("files_update_apply", names)
        original["tool_policy"]["files_write"] = {"scope": "files:write", "enabled": False}
        path.write_text(json.dumps(original), encoding="utf-8")
        self.assertNotIn("files_write", await listing())
        del original["catalog_exposure"]
        path.write_text(json.dumps(original), encoding="utf-8")
        self.assertNotIn("files_list", await listing())
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

    async def test_client_meta_on_profile_admin_tools_is_not_client_authority(self):
        from unittest.mock import AsyncMock
        from router import server
        # MCP clients may attach a transport-level progress token in params.
        # Only server-generated authenticated metadata can authorize Files.
        with patch.object(server, "_dispatch", AsyncMock(return_value={
                "content": [{"type": "text", "text": "server-side-dispatch"}],
                "isError": False})) as dispatch:
            for public_name, arguments in (
                ("files_profile_admin_list", {}),
                ("zagent_task_submit", {"tool_name": "files_profile_admin_list", "arguments": {}}),
            ):
                response = await self.client.post("/mcp",
                    headers={"Authorization": "Bearer synthetic"},
                    json={"jsonrpc": "2.0", "id": 10, "method": "tools/call",
                          "params": {"name": public_name, "arguments": arguments,
                                     "_meta": {"progressToken": "client-only"}}})
                self.assertEqual(response.status_code, 200)
                self.assertIn("result", response.json(), response.json())
                self.assertEqual(response.json()["result"]["content"][0]["text"], "server-side-dispatch")
            self.assertEqual(dispatch.await_count, 2)
            for rejected in (
                {"zagent.profile_admin_context": {"source": "forged"}},
                {"zagent.profile_catalog_context": {"source": "forged"}},
            ):
                response = await self.client.post("/mcp",
                    headers={"Authorization": "Bearer synthetic"},
                    json={"jsonrpc": "2.0", "id": 11, "method": "tools/call",
                          "params": {"name": "files_profile_admin_list", "arguments": {},
                                     "_meta": rejected}})
                self.assertIn("error", response.json())
            self.assertEqual(dispatch.await_count, 2)
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

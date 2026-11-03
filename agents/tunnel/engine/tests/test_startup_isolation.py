"""Independent Router upstream recovery; no live services or credentials."""
import asyncio
import unittest

from router.registry import MCPRegistry, UpstreamState


def service(name):
    return {"id": name, "name": name, "namespace": name, "enabled": True,
            "url": "http://127.0.0.1:18999/mcp", "internal_auth": False}


class StartupIsolationTests(unittest.IsolatedAsyncioTestCase):
    def new_registry(self):
        registry = object.__new__(MCPRegistry)
        registry.states = {
            "files": UpstreamState(service("files"), initialized=True,
                                   tools=[{"name": "files_stat"}]),
            "web": UpstreamState(service("web"), initialized=False,
                                 tools=[], last_error="temporarily unavailable"),
        }
        registry.tool_index = {}
        registry.clients = {}
        registry.rebuild_index()
        return registry

    async def test_partial_catalog_recovers_without_router_restart(self):
        registry = self.new_registry()
        self.assertIn("files_stat", registry.tool_index)
        self.assertNotIn("web_ping", registry.tool_index)
        recovered = asyncio.Event()
        calls = []

        async def refresh(service_id):
            calls.append(service_id)
            state = registry.states[service_id]
            state.initialized = True
            state.last_error = ""
            state.tools = [{"name": "web_ping"}]
            registry.rebuild_index()
            recovered.set()
            return {"ok": True, "tools": 1}

        registry.refresh_service = refresh
        background = asyncio.create_task(registry.retry_unavailable(0.01))
        try:
            await asyncio.wait_for(recovered.wait(), timeout=2)
        finally:
            background.cancel()
            await asyncio.gather(background, return_exceptions=True)

        self.assertEqual(["web"], calls)
        self.assertIn("files_stat", registry.tool_index)
        self.assertIn("web_ping", registry.tool_index)

    async def test_refresh_is_serialized_per_upstream(self):
        registry = self.new_registry()
        concurrent = 0
        maximum = 0

        async def refresh_inner(state):
            nonlocal concurrent, maximum
            concurrent += 1
            maximum = max(maximum, concurrent)
            await asyncio.sleep(0.01)
            concurrent -= 1
            return {"ok": True, "tools": 1}

        registry._refresh_service_unlocked = refresh_inner
        await asyncio.gather(registry.refresh_service("web"),
                             registry.refresh_service("web"))
        self.assertEqual(1, maximum)


if __name__ == "__main__":
    unittest.main()

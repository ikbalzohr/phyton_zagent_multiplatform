import copy
import unittest

from mcp_server.request_context import correlation
from mcp_server.tools import goals as goal_tools
from orchestrator.compiler import compile_plan


GOAL = {
    "schema_version": "2.0",
    "goal_type": "build_map",
    "raw_goal": "Susun peta administrasi Fixture Company",
    "target_mode": "CURRENT",
    "crs": "EPSG:32750",
    "outputs": {"formats": ["PDF", "PNG"], "dpi": 400, "save_mxd": False},
    "dry_run": True,
}


class FakeMCP:
    def __init__(self):
        self.tools = {}

    def tool(self):
        def decorator(fn):
            self.tools[fn.__name__] = fn
            return fn
        return decorator


class FakeRuntime:
    def __init__(self):
        self.calls = []

    def submit(self, plan, owner, idempotency_key=None, priority=1):
        self.calls.append(("submit", plan, owner, idempotency_key, priority))
        return {"ok": True, "status": "QUEUED", "run_id": "run_1", "task_id": "task_1"}

    def status(self, run_id, session_id):
        self.calls.append(("status", run_id, session_id))
        return {"ok": True, "status": "RUNNING", "run_id": run_id}

    def resume(self, run_id, session_id, review_decision=None):
        self.calls.append(("resume", run_id, session_id, review_decision))
        return {"ok": True, "status": "PREFLIGHT", "run_id": run_id}

    def cancel(self, run_id, session_id):
        self.calls.append(("cancel", run_id, session_id))
        return {"ok": True, "status": "CANCEL_REQUESTED", "run_id": run_id}

    def report(self, run_id, session_id):
        self.calls.append(("report", run_id, session_id))
        return {"ok": True, "status": "RUNNING", "data": {"run_id": run_id}}


class FakeServices:
    def __init__(self, runtime=None):
        self.calls = []
        if runtime is not None:
            self.goal_runtime = runtime

    def call(self, action, kind="read", **payload):
        self.calls.append((action, kind, dict(payload)))
        data = {
            "ping": {"ok": True, "revision": "r1"},
            "status": {"ok": True, "document_revision": "r1"},
            "inspect_current_map": {"ok": True, "crs": "EPSG:32750"},
            "list_layers": {"ok": True, "layers": []},
            "list_layout_elements": {"ok": True, "elements": []},
            "get_dataframe_state": {"ok": True, "data_frame": "Layers", "spatial_reference": {"wkid": 32750}},
        }
        return data[action]


class GoalFacadeTests(unittest.TestCase):
    def setUp(self):
        self.mcp = FakeMCP()
        self.services = FakeServices()
        goal_tools.register(self.mcp, self.services)

    def _plan(self):
        context = {
            "available": True,
            "fingerprint": "fixture",
            "map": {"ok": True, "crs": "EPSG:32750"},
            "dataframe": {"spatial_reference": {"wkid": 32750}},
        }
        return compile_plan(copy.deepcopy(GOAL), context=context)["data"]

    def _bound(self):
        return correlation.set({
            "session_id": "owner_fixture_a",
            "device_id": "dev1",
            "principal_id": "principal-fixture",
            "workspace_id": "workspace-fixture",
            "resource_id": "map-fixture",
            "operation_id": "op-fixture",
            "request_id": "req1",
            "trace_id": "trc1",
            "task_id": "task_parent",
        })

    def test_registers_full_goal_surface(self):
        self.assertEqual(
            set(self.mcp.tools),
            {
                "arcmap_goal_plan",
                "arcmap_goal_validate",
                "arcmap_goal_build_map",
                "arcmap_goal_execute",
                "arcmap_goal_status",
                "arcmap_goal_resume",
                "arcmap_goal_cancel",
                "arcmap_goal_report",
            },
        )

    def test_execute_fails_closed_when_durable_runtime_is_missing(self):
        token = self._bound()
        try:
            result = self.mcp.tools["arcmap_goal_execute"](self._plan())
        finally:
            correlation.reset(token)
        self.assertFalse(result["ok"])
        self.assertEqual(result["errors"][0]["code"], "DURABLE_RUNTIME_UNAVAILABLE")
        self.assertEqual(self.services.calls, [])

    def test_build_map_dry_run_uses_read_only_context(self):
        result = self.mcp.tools["arcmap_goal_build_map"](copy.deepcopy(GOAL), dry_run=True)
        self.assertEqual(result["status"], "PLANNED")
        self.assertTrue(all(kind == "read" for _, kind, _ in self.services.calls))

    def test_goal_plan_uses_no_write_calls(self):
        result = self.mcp.tools["arcmap_goal_plan"](copy.deepcopy(GOAL))
        self.assertEqual(result["status"], "PLANNED")
        self.assertTrue(all(kind == "read" for _, kind, _ in self.services.calls))

    def test_goal_validate_is_pure_and_does_not_touch_services(self):
        plan = self._plan()
        before = list(self.services.calls)
        result = self.mcp.tools["arcmap_goal_validate"](copy.deepcopy(plan))
        self.assertTrue(result["ok"])
        self.assertEqual(before, self.services.calls)

    def test_execute_passes_authoritative_owner_to_runtime(self):
        runtime = FakeRuntime()
        services = FakeServices(runtime)
        mcp = FakeMCP()
        goal_tools.register(mcp, services)
        token = self._bound()
        try:
            result = mcp.tools["arcmap_goal_execute"](
                self._plan(), idempotency_key="idem", priority=3)
        finally:
            correlation.reset(token)
        self.assertTrue(result["ok"])
        call = runtime.calls[0]
        self.assertEqual(call[0], "submit")
        self.assertEqual(call[2]["session_id"], "owner_fixture_a")
        self.assertEqual(call[2]["device_id"], "dev1")
        self.assertEqual(call[3], "idem")
        self.assertEqual(call[4], 3)

    def test_status_resume_cancel_report_are_owner_scoped(self):
        runtime = FakeRuntime()
        services = FakeServices(runtime)
        mcp = FakeMCP()
        goal_tools.register(mcp, services)
        token = self._bound()
        try:
            self.assertEqual(mcp.tools["arcmap_goal_status"]("run_1")["status"], "RUNNING")
            self.assertEqual(
                mcp.tools["arcmap_goal_resume"]("run_1", {"decision": "continue"})["status"],
                "PREFLIGHT",
            )
            self.assertEqual(mcp.tools["arcmap_goal_cancel"]("run_1")["status"], "CANCEL_REQUESTED")
            self.assertEqual(mcp.tools["arcmap_goal_report"]("run_1")["status"], "RUNNING")
        finally:
            correlation.reset(token)
        self.assertTrue(all(call[2] == "owner_fixture_a" for call in runtime.calls if call[0] != "submit"))

    def test_execute_without_authoritative_metadata_is_denied(self):
        runtime = FakeRuntime()
        services = FakeServices(runtime)
        mcp = FakeMCP()
        goal_tools.register(mcp, services)
        result = mcp.tools["arcmap_goal_execute"](self._plan())
        self.assertFalse(result["ok"])
        self.assertEqual(result["errors"][0]["code"], "ACCESS_DENIED")
        self.assertEqual(runtime.calls, [])


if __name__ == "__main__":
    unittest.main()

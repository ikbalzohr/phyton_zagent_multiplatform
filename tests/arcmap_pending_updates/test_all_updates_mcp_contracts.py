"""MCP tool contract/unit tests for all ArcMap pending updates (NOT EXECUTED)."""
import importlib.util
import os
import unittest

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
_TOOL_ROOT = os.path.join(_ROOT, "agents", "arcmap", "engine", "mcp_server", "tools")


class FakeMcp:
    def __init__(self):
        self.handlers = {}

    def tool(self):
        def register(func):
            if func.__name__ in self.handlers:
                raise AssertionError("Duplicate MCP tool: " + func.__name__)
            self.handlers[func.__name__] = func
            return func
        return register


class FakeServices:
    def __init__(self):
        self.calls = []

    def call(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return {"ok": True, "kind": args[1] if len(args) > 1 else "read"}


def load(name):
    path = os.path.join(_TOOL_ROOT, name + ".py")
    spec = importlib.util.spec_from_file_location("unit_" + name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class AllArcMapMcpContracts(unittest.TestCase):
    def setUp(self):
        self.mcp = FakeMcp()
        self.services = FakeServices()
        for name in ("smart_corner", "native_layer_properties", "native_grids"):
            load(name).register(self.mcp, self.services)

    def test_new_tool_names_are_unique_and_complete(self):
        self.assertEqual(19, len(self.mcp.handlers))  # Smart 7, Layer 6, Grid 6.
        for name in (
            "arcmap_smart_corner_preflight", "arcmap_smart_corner_preview",
            "arcmap_smart_corner_review", "arcmap_smart_corner_commit",
            "arcmap_smart_corner_validate", "arcmap_smart_corner_status",
            "arcmap_smart_corner_rollback", "arcmap_list_native_grids",
            "arcmap_get_native_grid_properties",
            "arcmap_set_native_grid_properties",
            "arcmap_restore_native_grid_state",
            "arcmap_get_native_layer_properties",
            "arcmap_set_native_unique_values_renderer",
        ):
            self.assertIn(name, self.mcp.handlers)

    def test_smart_corner_preflight_and_preview_remain_read_only(self):
        self.mcp.handlers["arcmap_smart_corner_preflight"]("polygon", "points")
        self.mcp.handlers["arcmap_smart_corner_preview"]("polygon", "points")
        for args, _ in self.services.calls:
            self.assertEqual(1, len(args))
        self.assertEqual(["smart_corner_preflight", "smart_corner_preview"],
                         [c[0][0] for c in self.services.calls])

    def test_smart_corner_commit_default_is_explicit_dry_run(self):
        self.mcp.handlers["arcmap_smart_corner_commit"]("preview", "revision", "some-request-123")
        args, data = self.services.calls[-1]
        self.assertEqual(("smart_corner_commit", "destructive"), args)
        self.assertTrue(data["dry_run"])
        self.assertFalse(data["confirm_commit"])
        self.assertFalse(data["confirm_replace_nonempty"])

    def test_commit_and_rollback_use_destructive_safety_gate(self):
        self.mcp.handlers["arcmap_smart_corner_commit"](
            "p", "r", "unique-key-12345", dry_run=False, confirm_commit=True)
        self.mcp.handlers["arcmap_smart_corner_rollback"]("a" * 32, confirm_rollback=True)
        self.assertEqual("destructive", self.services.calls[-2][0][1])
        self.assertEqual("destructive", self.services.calls[-1][0][1])

    def test_review_validate_status_are_read_only(self):
        self.mcp.handlers["arcmap_smart_corner_review"]("p", "r")
        self.mcp.handlers["arcmap_smart_corner_validate"](preview_id="p")
        self.mcp.handlers["arcmap_smart_corner_status"]("a" * 32)
        self.assertTrue(all(len(call[0]) == 1 for call in self.services.calls[-3:]))

    def test_native_grid_mutations_have_live_write_guard(self):
        self.mcp.handlers["arcmap_set_native_grid_properties"](
            grid_name="Existing", properties={"x_interval": 1 / 120, "y_interval": 1 / 120})
        self.mcp.handlers["arcmap_create_native_grid"]("New")
        self.mcp.handlers["arcmap_remove_native_grid"]("Existing", confirm_remove=True)
        self.mcp.handlers["arcmap_restore_native_grid_state"]("some-token")
        self.assertTrue(all(call[0][1] == "live_write"
                            for call in self.services.calls[-4:]))

    def test_native_renderer_mutations_have_live_write_guard(self):
        self.mcp.handlers["arcmap_set_native_unique_values_renderer"](
            layer_name="Land", field_name="KELAS", show_other_values=False)
        self.mcp.handlers["arcmap_update_native_category"]("Land", "PIPPIB PRIMER")
        self.assertTrue(all(c[0][1] == "live_write" for c in self.services.calls[-2:]))

    def test_edit_existing_grid_keeps_explicit_locator_and_interval(self):
        self.mcp.handlers["arcmap_set_native_grid_properties"](
            grid_name="MyGraticule", properties={"x_interval": 1 / 120, "y_interval": 1 / 120})
        _, data = self.services.calls[-1]
        self.assertEqual("MyGraticule", data["grid_name"])
        self.assertEqual(1 / 120, data["properties"]["y_interval"])

    def test_no_mxd_save_tool_in_new_mcp(self):
        for name in self.mcp.handlers:
            self.assertNotIn("save_mxd", name)


if __name__ == "__main__":
    unittest.main()

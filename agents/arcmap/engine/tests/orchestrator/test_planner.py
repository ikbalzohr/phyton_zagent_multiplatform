import copy
import unittest

from orchestrator.planner import plan_goal, validate_plan


GOAL = {
    "schema_version": "2.0",
    "goal_type": "build_map",
    "raw_goal": "Susun peta administrasi PT Buol Agri Lestari",
    "target_mode": "CURRENT",
    "layout": {"paper": "A4", "orientation": "landscape"},
    "outputs": {"formats": ["PDF", "PNG"], "dpi": 400, "save_mxd": False},
    "dry_run": True,
    "source_edit_policy": "read_only",
}


class FakeServices:
    def __init__(self, fail_action=None):
        self.fail_action = fail_action
        self.calls = []

    def call(self, action, kind="read", **payload):
        self.calls.append((action, kind))
        if action == self.fail_action:
            return {"ok": False, "error": "fixture unavailable"}
        data = {
            "ping": {"ok": True, "revision": "r1"},
            "status": {"ok": True, "document_revision": "r1"},
            "inspect_current_map": {"ok": True, "crs": "EPSG:32750"},
            "list_layers": {"ok": True, "layers": []},
            "list_layout_elements": {"ok": True, "elements": []},
            "get_dataframe_state": {"ok": True, "data_frame": "Layers", "spatial_reference": {"wkid": 32750}},
        }
        return data[action]


class PlannerTests(unittest.TestCase):
    def test_plan_goal_returns_deterministic_plan_without_writes(self):
        s1 = FakeServices()
        s2 = FakeServices()
        a = plan_goal(s1, copy.deepcopy(GOAL))
        b = plan_goal(s2, copy.deepcopy(GOAL))
        self.assertEqual(a["status"], "PLANNED")
        self.assertEqual(a["plan_hash"], b["plan_hash"])
        self.assertTrue(all(kind == "read" for _, kind in s1.calls))
        self.assertTrue(all(n["effect_class"] == "read" for n in a["data"]["nodes"] if n["selected_for_dry_run"]))

    def test_unavailable_current_context_blocks_current_strategy(self):
        result = plan_goal(FakeServices("status"), copy.deepcopy(GOAL))
        self.assertEqual(result["status"], "BLOCKED")
        self.assertTrue(any(e["code"] == "CONTEXT_INCOMPLETE" for e in result["errors"]))

    def test_validate_plan_accepts_compiler_output(self):
        result = plan_goal(FakeServices(), copy.deepcopy(GOAL))
        validated = validate_plan(copy.deepcopy(result["data"]))
        self.assertTrue(validated["ok"])
        self.assertEqual(validated["status"], "PLANNED")

    def test_validate_plan_detects_tamper(self):
        result = plan_goal(FakeServices(), copy.deepcopy(GOAL))
        plan = copy.deepcopy(result["data"])
        plan["goal"]["raw_goal"] = "tampered"
        validated = validate_plan(plan)
        self.assertFalse(validated["ok"])
        self.assertTrue(any(e["code"] == "PLAN_HASH_MISMATCH" for e in validated["errors"]))


if __name__ == "__main__":
    unittest.main()

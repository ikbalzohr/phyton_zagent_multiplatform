import copy
import unittest

from orchestrator.compiler import compile_plan, normalize_goal, validate_goal


BASE = {
    "schema_version": "2.0",
    "goal_type": "build_map",
    "raw_goal": "Fixture map",
    "target_mode": "CURRENT",
    "crs": "EPSG:32750",
    "dry_run": True,
}

CTX = {
    "available": True,
    "fingerprint": "fixture",
    "map": {"ok": True, "crs": "EPSG:32750"},
}


class CompilerExtendedTests(unittest.TestCase):
    def test_defaults_are_normalized(self):
        g = normalize_goal(copy.deepcopy(BASE))
        self.assertEqual(g["layout"]["paper"], "A4")
        self.assertEqual(g["outputs"]["dpi"], 400)
        self.assertEqual(g["save_policy"], "none")
        self.assertEqual(g["source_edit_policy"], "read_only")

    def test_template_strategy_requires_template_and_data_root(self):
        g = copy.deepcopy(BASE)
        g["target_mode"] = "TEMPLATE"
        r = compile_plan(g, context=CTX)
        codes = {e["code"] for e in r["errors"]}
        self.assertEqual(r["status"], "BLOCKED")
        self.assertIn("TEMPLATE_REQUIRED", codes)
        self.assertIn("DATA_ROOT_REQUIRED", codes)

    def test_blank_strategy_requires_data_root(self):
        g = copy.deepcopy(BASE)
        g["target_mode"] = "NEW_DOCUMENT"
        r = compile_plan(g, context=CTX)
        self.assertEqual(r["status"], "BLOCKED")
        self.assertTrue(any(e["code"] == "DATA_ROOT_REQUIRED" for e in r["errors"]))

    def test_template_strategy_uses_file_worker_probe(self):
        g = copy.deepcopy(BASE)
        g["target_mode"] = "TEMPLATE"
        g["template_mxd"] = r"C:\fixture\template.mxd"
        g["data_root"] = r"C:\fixture\data"
        r = compile_plan(g, context=CTX)
        self.assertEqual(r["status"], "PLANNED")
        steps = {x["step_id"]: x for x in r["data"]["nodes"]}
        self.assertEqual(steps["s010"]["action"], "orchestrator.file_worker_probe")
        self.assertEqual(steps["s010"]["lane"], "file_worker")

    def test_blank_strategy_uses_file_worker_probe(self):
        g = copy.deepcopy(BASE)
        g["target_mode"] = "NEW_DOCUMENT"
        g["target_disposable"] = True
        g["data_root"] = r"C:\fixture\data"
        r = compile_plan(g, context=CTX)
        self.assertEqual(r["status"], "PLANNED")
        steps = {x["step_id"]: x for x in r["data"]["nodes"]}
        self.assertEqual(steps["s010"]["action"], "orchestrator.file_worker_probe")
        self.assertEqual(steps["s010"]["lane"], "file_worker")

    def test_layout_only_uses_strategy_d(self):
        g = copy.deepcopy(BASE)
        g["goal_type"] = "layout_only"
        r = compile_plan(g, context=CTX)
        self.assertEqual(r["status"], "PLANNED")
        self.assertEqual(r["data"]["strategy"], "D_LAYOUT_ONLY")

    def test_invalid_goal_fails_before_plan_generation(self):
        g = copy.deepcopy(BASE)
        g["target_mode"] = "INVALID"
        errors = validate_goal(normalize_goal(g))
        self.assertTrue(any(e["code"] == "INVALID_TARGET_MODE" for e in errors))
        r = compile_plan(g, context=CTX)
        self.assertEqual(r["status"], "INVALID")
        self.assertIsNone(r["data"])


if __name__ == "__main__":
    unittest.main()

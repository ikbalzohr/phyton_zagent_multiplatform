import copy
import unittest

from orchestrator.compiler import compile_plan, validate_compiled_plan

CONTEXT = {
    "schema_version":"2.0",
    "available":True,
    "collected_at":0,
    "source":"arcmap-live-readonly",
    "fingerprint":"fixture-context-v1",
    "map":{"ok":True,"crs":"EPSG:32750"},
}

GOAL = {
    "schema_version":"2.0",
    "goal_type":"build_map",
    "raw_goal":"Susun peta administrasi PT Buol Agri Lestari dari data yang tersedia",
    "target_mode":"CURRENT",
    "required_layer_roles":["batas_perusahaan","jalan","sungai","desa"],
    "layout":{"paper":"A4","orientation":"landscape"},
    "outputs":{"formats":["PDF","PNG"],"dpi":400,"save_mxd":False},
    "dry_run":True,
    "max_repair_cycles":3,
    "source_edit_policy":"read_only",
}

class CompilerTests(unittest.TestCase):
    def test_deterministic(self):
        a = compile_plan(copy.deepcopy(GOAL), context=copy.deepcopy(CONTEXT))
        b = compile_plan(copy.deepcopy(GOAL), context=copy.deepcopy(CONTEXT))
        self.assertEqual(a["plan_hash"], b["plan_hash"])
        self.assertEqual(a["plan_id"], b["plan_id"])
        self.assertEqual(a["status"], "PLANNED")

    def test_dry_run_selection_has_no_write(self):
        r = compile_plan(copy.deepcopy(GOAL), context=copy.deepcopy(CONTEXT))
        selected = [n for n in r["data"]["nodes"] if n.get("selected_for_dry_run")]
        self.assertTrue(selected)
        self.assertTrue(all(n["effect_class"] == "read" for n in selected))

    def test_dry_run_is_dependency_closed(self):
        r = compile_plan(copy.deepcopy(GOAL), context=copy.deepcopy(CONTEXT))
        by_id = {n["step_id"]: n for n in r["data"]["nodes"]}
        self.assertFalse(by_id["s100"]["selected_for_dry_run"])
        self.assertFalse(by_id["s200"]["selected_for_dry_run"])
        selected = set(r["data"]["dry_run_nodes"])
        for node in r["data"]["nodes"]:
            if node.get("selected_for_dry_run"):
                self.assertTrue(all(dep in selected for dep in node["dependencies"]))

    def test_dataframe_spatial_reference_resolves_crs_gate(self):
        goal = copy.deepcopy(GOAL)
        ctx = copy.deepcopy(CONTEXT)
        ctx["map"] = {"ok": True}
        ctx["dataframe"] = {"ok": True, "spatial_reference": {"wkid": 32651, "name": "WGS_1984_UTM_Zone_51N"}}
        r = compile_plan(goal, context=ctx)
        self.assertEqual(r["status"], "PLANNED")
        self.assertFalse(any(x.get("code") == "CRS_REQUIRED_BEFORE_EXECUTE" for x in r["errors"]))

    def test_current_unavailable_blocks(self):
        ctx = dict(CONTEXT)
        ctx["available"] = False
        r = compile_plan(copy.deepcopy(GOAL), context=ctx)
        self.assertEqual(r["status"], "BLOCKED")
        self.assertTrue(any(x["code"] == "CONTEXT_INCOMPLETE" for x in r["errors"]))

    def test_plan_hash_detects_change(self):
        r = compile_plan(copy.deepcopy(GOAL), context=copy.deepcopy(CONTEXT))
        plan = copy.deepcopy(r["data"])
        plan["goal"]["raw_goal"] = "changed"
        errors = validate_compiled_plan(plan)
        self.assertTrue(any(x["code"] == "PLAN_HASH_MISMATCH" for x in errors))

if __name__ == "__main__":
    unittest.main()

import copy
import random
import unittest

from orchestrator.capabilities import primitive_map
from orchestrator.compiler import compile_plan


CTX = {
    "available": True,
    "fingerprint": "fixture-context-v2",
    "map": {"ok": True, "crs": "EPSG:32750"},
    "dataframe": {"ok": True, "spatial_reference": {"wkid": 32750}},
}


def goal_for(mode="CURRENT", goal_type="build_map"):
    goal = {
        "schema_version": "2.0",
        "goal_type": goal_type,
        "raw_goal": "Invariant fixture",
        "target_mode": mode,
        "crs": "EPSG:32750",
        "dry_run": True,
        "source_edit_policy": "read_only",
    }
    if mode == "TEMPLATE":
        goal["template_mxd"] = r"D:\fixture\template.mxd"
        goal["data_root"] = r"D:\fixture\data"
    elif mode == "NEW_DOCUMENT":
        goal["data_root"] = r"D:\fixture\data"
    return goal


class PlanInvariantTests(unittest.TestCase):
    def _plans(self):
        cases = [
            goal_for("CURRENT", "build_map"),
            goal_for("TEMPLATE", "build_map"),
            goal_for("NEW_DOCUMENT", "build_map"),
            goal_for("CURRENT", "layout_only"),
        ]
        return [compile_plan(g, context=copy.deepcopy(CTX))["data"] for g in cases]

    def test_step_ids_are_unique_and_dependencies_point_backward(self):
        for plan in self._plans():
            seen = set()
            for node in plan["nodes"]:
                self.assertNotIn(node["step_id"], seen)
                self.assertTrue(all(dep in seen for dep in node["dependencies"]))
                seen.add(node["step_id"])

    def test_every_action_exists_in_capability_manifest(self):
        caps = primitive_map()
        for plan in self._plans():
            missing = [n["action"] for n in plan["nodes"] if n["action"] not in caps]
            self.assertEqual(missing, [])

    def test_dry_run_nodes_are_read_only_and_dependency_closed(self):
        for plan in self._plans():
            selected = {n["step_id"] for n in plan["nodes"] if n["selected_for_dry_run"]}
            for node in plan["nodes"]:
                if node["step_id"] in selected:
                    self.assertEqual(node["effect_class"], "read")
                    self.assertTrue(set(node["dependencies"]) <= selected)

    def test_no_publish_or_write_is_selected_for_dry_run(self):
        forbidden = {"live_write", "file_write", "save", "export", "publish"}
        for plan in self._plans():
            selected = [n for n in plan["nodes"] if n["selected_for_dry_run"]]
            self.assertFalse(any(n["effect_class"] in forbidden for n in selected))

    def test_repeated_compilation_is_deterministic(self):
        goal = goal_for("CURRENT", "build_map")
        hashes = {
            compile_plan(copy.deepcopy(goal), context=copy.deepcopy(CTX))["plan_hash"]
            for _ in range(50)
        }
        self.assertEqual(len(hashes), 1)

    def test_dict_key_order_does_not_change_plan_hash(self):
        goal = goal_for("CURRENT", "build_map")
        items = list(goal.items())
        random.Random(42).shuffle(items)
        shuffled = dict(items)
        a = compile_plan(copy.deepcopy(goal), context=copy.deepcopy(CTX))
        b = compile_plan(shuffled, context=copy.deepcopy(CTX))
        self.assertEqual(a["plan_hash"], b["plan_hash"])


if __name__ == "__main__":
    unittest.main()

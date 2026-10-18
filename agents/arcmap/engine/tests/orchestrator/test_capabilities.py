import copy
import unittest

from orchestrator.capabilities import (
    load_manifest,
    manifest_hash,
    primitive_map,
    validate_plan_capabilities,
)


class CapabilityPolicyTests(unittest.TestCase):
    def test_manifest_contains_core_o1_primitives(self):
        caps = primitive_map()
        for name in (
            "orchestrator.validate_goal",
            "arcmap_ping",
            "arcmap_get_status",
            "arcmap_inspect_current_map",
            "arcmap_list_layers",
            "arcmap_list_layout_elements",
            "orchestrator.final_validate",
        ):
            self.assertIn(name, caps)

    def test_manifest_hash_is_deterministic(self):
        manifest = load_manifest()
        self.assertEqual(manifest_hash(manifest), manifest_hash(copy.deepcopy(manifest)))

    def test_unknown_capability_is_rejected(self):
        plan = {"nodes": [{
            "step_id": "x",
            "action": "arcmap_nonexistent",
            "lane": "pure",
            "effect_class": "read",
            "selected_for_dry_run": True,
        }]}
        errors = validate_plan_capabilities(plan, dry_run=True)
        self.assertEqual(errors[0]["code"], "CAPABILITY_UNAVAILABLE")

    def test_lane_and_effect_mismatch_are_rejected(self):
        plan = {"nodes": [{
            "step_id": "x",
            "action": "arcmap_ping",
            "lane": "pure",
            "effect_class": "live_write",
            "selected_for_dry_run": True,
        }]}
        codes = {e["code"] for e in validate_plan_capabilities(plan, dry_run=True)}
        self.assertIn("CAPABILITY_LANE_MISMATCH", codes)
        self.assertIn("CAPABILITY_EFFECT_MISMATCH", codes)

    def test_dry_run_blocks_selected_write_capability(self):
        plan = {"nodes": [{
            "step_id": "x",
            "action": "orchestrator.execute_strategy_a",
            "lane": "live",
            "effect_class": "live_write",
            "selected_for_dry_run": True,
        }]}
        codes = {e["code"] for e in validate_plan_capabilities(plan, dry_run=True)}
        self.assertIn("DRY_RUN_WRITE_BLOCKED", codes)


if __name__ == "__main__":
    unittest.main()

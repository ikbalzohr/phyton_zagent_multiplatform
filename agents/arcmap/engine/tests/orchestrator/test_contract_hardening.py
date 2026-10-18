import copy
import unittest

from orchestrator.capabilities import load_manifest
from orchestrator.compiler import compile_plan
from orchestrator.contracts import load_schema
from orchestrator.errors import MANDATORY_ERROR_CODES, KNOWN_ERROR_CODES, error


MANDATORY = {
    "ACCESS_DENIED",
    "TARGET_STALE",
    "CONTEXT_INCOMPLETE",
    "CAPABILITY_UNAVAILABLE",
    "LICENSE_UNAVAILABLE",
    "DATA_INVALID",
    "LOCK_CONFLICT",
    "DEADLINE_EXCEEDED",
    "OUTCOME_UNKNOWN",
    "VALIDATION_FAILED",
    "ARTIFACT_INVALID",
    "PUBLISH_PARTIAL",
    "RECOVERY_REQUIRED",
}


class ContractHardeningTests(unittest.TestCase):
    def test_error_taxonomy_contains_all_master_plan_minimum_codes(self):
        self.assertEqual(MANDATORY_ERROR_CODES, frozenset(MANDATORY))
        self.assertTrue(MANDATORY <= KNOWN_ERROR_CODES)

    def test_error_helper_is_structured(self):
        e = error("TARGET_STALE", "revision changed", details={"expected":"r1","actual":"r2"})
        self.assertEqual(e["code"], "TARGET_STALE")
        self.assertFalse(e["retryable"])
        self.assertEqual(e["details"]["actual"], "r2")

    def test_result_schema_contains_durable_run_states(self):
        schema = load_schema("result.schema.json")
        states = set(schema["properties"]["status"]["enum"])
        required = {
            "PLANNED","PREFLIGHT","QUEUED","RUNNING","VALIDATING","STAGING","PUBLISHING",
            "SUCCEEDED","BLOCKED","WAITING_FOR_REVIEW","REPAIRING","CANCEL_REQUESTED",
            "RECONCILING","FAILED","CANCELLED","ROLLED_BACK","RECOVERY_REQUIRED",
            "ARTIFACT_INVALID","PUBLISH_PARTIAL",
        }
        self.assertTrue(required <= states)

    def test_goal_schema_matches_strategy_c_and_style_contract(self):
        schema = load_schema("goal.schema.json")
        props = schema["properties"]
        self.assertIn("target_disposable", props)
        self.assertIn("style_profile", props)
        self.assertEqual(props["max_repair_cycles"]["maximum"], 3)
        self.assertFalse(schema["additionalProperties"])

    def test_compiler_rejects_repair_budget_over_three(self):
        goal = {
            "schema_version":"2.0",
            "goal_type":"build_map",
            "raw_goal":"fixture",
            "target_mode":"CURRENT",
            "crs":"EPSG:32750",
            "max_repair_cycles":4,
        }
        context = {"available":True,"fingerprint":"f","map":{"crs":"EPSG:32750"}}
        r = compile_plan(copy.deepcopy(goal), context=context)
        self.assertEqual(r["status"], "INVALID")
        self.assertTrue(any(x["code"]=="INVALID_REPAIR_BUDGET" for x in r["errors"]))

    def test_every_capability_has_master_plan_metadata(self):
        manifest = load_manifest()
        required = {
            "input_schema","output_schema","availability","runtime","licenses","extensions",
            "idempotency_class","reconciliation_probe","rollback_coverage","resource_scope",
            "estimated_cost_class","dry_run_eligible","effect_class","lane",
        }
        for item in manifest["primitives"]:
            missing = sorted(required - set(item))
            self.assertEqual(missing, [], item["name"])

    def test_facade_manifest_lists_exact_goal_surface(self):
        names = {x["name"] for x in load_manifest().get("facades") or []}
        self.assertEqual(names, {
            "arcmap_goal_build_map",
            "arcmap_goal_plan",
            "arcmap_goal_validate",
            "arcmap_goal_execute",
            "arcmap_goal_status",
            "arcmap_goal_resume",
            "arcmap_goal_cancel",
            "arcmap_goal_report",
        })


if __name__ == "__main__":
    unittest.main()

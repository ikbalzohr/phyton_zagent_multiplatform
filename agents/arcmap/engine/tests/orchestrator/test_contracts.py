import json
import unittest

from orchestrator.contracts import available_schemas, load_schema, SCHEMA_VERSION


class ContractTests(unittest.TestCase):
    def test_all_contracts_load_as_json_objects(self):
        schemas = available_schemas()
        self.assertEqual(set(schemas), {"goal", "context", "plan", "result", "validation"})
        for name, schema in schemas.items():
            self.assertIsInstance(schema, dict, name)
            self.assertIn("$schema", schema)
            self.assertIn("type", schema)
            json.dumps(schema, sort_keys=True)

    def test_schema_version_is_v2(self):
        self.assertEqual(SCHEMA_VERSION, "2.0")
        self.assertEqual(load_schema("goal.schema.json")["properties"]["schema_version"]["const"], "2.0")
        self.assertEqual(load_schema("context.schema.json")["properties"]["schema_version"]["const"], "2.0")
        self.assertEqual(load_schema("plan.schema.json")["properties"]["schema_version"]["const"], "2.0")

    def test_goal_contract_fail_closed_for_unknown_fields(self):
        goal_schema = load_schema("goal.schema.json")
        self.assertFalse(goal_schema["additionalProperties"])
        for required in ("schema_version", "goal_type", "raw_goal", "target_mode"):
            self.assertIn(required, goal_schema["required"])

    def test_plan_contract_contains_dag_and_effect_fields(self):
        plan_schema = load_schema("plan.schema.json")
        item = plan_schema["properties"]["nodes"]["items"]
        required = set(item["required"])
        self.assertTrue({"step_id", "action", "dependencies", "lane", "effect_class", "dry_run_eligible"} <= required)


if __name__ == "__main__":
    unittest.main()

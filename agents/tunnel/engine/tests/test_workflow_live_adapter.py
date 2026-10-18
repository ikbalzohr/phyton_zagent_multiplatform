import unittest
import os
from unittest.mock import patch

from router.workflow_live_adapter import ProductionArcMapLiveAdapter
from router.workflow_security import execution_authority


class FakeClient:
    def __init__(self):
        self.calls=[]
        self.context={
            "pid":123,
            "document_path":r"D:\safe\map.mxd",
            "document_id":"doc1",
            "bridge_instance_id":"bridge1",
        }

    def call(self,name,arguments=None):
        self.calls.append((name,arguments or {}))
        if name=="arcmap_ping":
            return {"ok":True,"context":dict(self.context)}
        if name=="arcmap_snapshot_state":
            return {
                "ok":True,
                "snapshot_id":"snap1",
                "restorable":["layer_visibility","layout_text"],
                "not_restored_by_design":["symbology"],
            }
        if name=="arcmap_validate_map_recipe":
            return {"ok":True}
        if name=="arcmap_apply_map_recipe":
            return {"ok":True,"run_id":"recipe1"}
        if name=="arcmap_restore_snapshot":
            return {"ok":True,"restored":True}
        if name=="arcmap_export_bundle":
            return {
                "ok":True,
                "files":[
                    {"format":"pdf","path":r"D:\stage\a.pdf"},
                    {"format":"png","path":r"D:\stage\a.png"},
                ],
            }
        raise AssertionError(name)


class LiveAdapterTests(unittest.TestCase):
    def setUp(self):
        self.client=FakeClient()
        context={"context_version":1,"principal_id":"p","workspace_id":"w",
                 "device_id":"d","installation_id":"i","request_id":"r","trace_id":"tr",
                 "task_id":"t","operation_id":"o","policy_revision":"1",
                 "required_scope":"arcmap:inspect","public_tool":"arcmap_goal_validate",
                 "deadline":9e18,"scopes":[],"effective_resources":[{"resource_id":"installation:i","kind":"arcmap"}],
                 "effective_access":"write"}
        patcher=patch.dict(os.environ,{"ZAGENT_INTERNAL_TOKEN":"synthetic-internal-token-0123456789"})
        patcher.start(); self.addCleanup(patcher.stop)
        self.a=ProductionArcMapLiveAdapter(self.client)
        self.authority=execution_authority(context, lambda:None)
        self.authority.__enter__(); self.addCleanup(self.authority.__exit__,None,None,None)
        self.expected={
            "instance_id":"bridge1",
            "document_id":"doc1",
            "document_path":r"D:\safe\map.mxd",
            "pid":123,
        }

    def test_identity_and_snapshot_are_target_locked(self):
        ident=self.a.inspect_identity()
        self.assertTrue(ident["ok"])
        self.assertEqual(ident["instance_id"],"bridge1")
        snap=self.a.snapshot_state(expected_context=self.expected)
        self.assertTrue(snap["ok"])
        self.assertIn("live_state",snap["coverage"])
        self.assertEqual(snap["snapshot_id"],"snap1")

    def test_stale_target_blocks_before_mutation(self):
        stale=dict(self.expected)
        stale["document_id"]="other"
        r=self.a.apply_recipe(
            {"operations":[]},
            expected_context=stale,
            fencing_epoch=1)
        self.assertFalse(r["ok"])
        self.assertEqual(r["code"],"TARGET_STALE")
        self.assertFalse(any(x[0]=="arcmap_apply_map_recipe"
                             for x in self.client.calls))

    def test_nonrestorable_symbology_recipe_is_blocked(self):
        r=self.a.validate_recipe({
            "operations":[{
                "action":"set_class_breaks",
                "params":{},
            }]
        })
        self.assertFalse(r["ok"])
        self.assertEqual(
            r["code"],"ROLLBACK_COVERAGE_INSUFFICIENT")

    def test_reversible_recipe_and_restore_are_forwarded(self):
        recipe={"operations":[{
            "action":"set_layer_visibility",
            "params":{"layer_name":"L","visible":True},
        }]}
        self.assertTrue(self.a.validate_recipe(recipe)["ok"])
        applied=self.a.apply_recipe(
            recipe,
            expected_context=self.expected,
            fencing_epoch=7)
        self.assertTrue(applied["ok"])
        self.assertEqual(applied["fencing_epoch"],7)
        restored=self.a.restore_snapshot(
            {"snapshot_id":"snap1"},
            expected_context=self.expected,
            fencing_epoch=7)
        self.assertTrue(restored["ok"])

if __name__=="__main__":
    unittest.main()

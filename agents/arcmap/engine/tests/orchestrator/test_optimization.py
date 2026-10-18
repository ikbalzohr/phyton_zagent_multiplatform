import unittest

from orchestrator.optimization import (
    RevisionCache, WorkerBudget, choose_worker, coalesce_refresh,
    context_projection, timing_breakdown, choose_ipc_mode,
)

class OptimizationTests(unittest.TestCase):
    def test_revision_cache_key_includes_revision_and_tool_hash(self):
        c=RevisionCache(max_items=2)
        k1=c.key("d","i","r1","t1"); k2=c.key("d","i","r2","t1")
        c.put(k1,{"x":1})
        self.assertEqual(c.get(k1),{"x":1}); self.assertIsNone(c.get(k2))

    def test_cache_invalidation_by_document_instance(self):
        c=RevisionCache()
        c.put(c.key("d","i","r1","t"),1); c.put(c.key("d","j","r1","t"),2)
        self.assertEqual(c.invalidate_document("d","i"),1); self.assertEqual(len(c),1)

    def test_worker_budget_blocks_nested_parallelism(self):
        b=WorkerBudget(max_workers=2,max_memory_mb=1024,allow_nested_parallelism=False)
        r=b.admit({"estimated_memory_mb":100,"parallel_processing_factor":2})
        self.assertFalse(r.ok); self.assertEqual(r.code,"NESTED_PARALLELISM_FORBIDDEN")

    def test_worker_budget_blocks_memory_overrun(self):
        r=WorkerBudget(max_workers=1,max_memory_mb=256).admit({"estimated_memory_mb":512})
        self.assertEqual(r.code,"MEMORY_BUDGET")

    def test_choose_worker_requires_proven_capability(self):
        probes=[
            {"ok":True,"bitness":32,"licenses":["Basic"],"extensions":[],"supported_tools":["Buffer"]},
            {"ok":True,"bitness":64,"licenses":["Basic"],"extensions":["Spatial"],"supported_tools":["Buffer","Project"]},
        ]
        r=choose_worker(probes,{"licenses":["Basic"],"extensions":["Spatial"],"tools":["Project"]})
        self.assertTrue(r["ok"]); self.assertEqual(r["worker"]["bitness"],64)
        self.assertFalse(choose_worker(probes,{"tools":["Unknown"]})["ok"])

    def test_refresh_operations_are_coalesced_once(self):
        ops=[{"action":"set_title"},{"action":"refresh_view"},{"action":"refresh_toc"},{"action":"set_scale"}]
        out=coalesce_refresh(ops)
        self.assertEqual(sum(1 for x in out if x["action"]=="refresh"),1)
        self.assertEqual(out[-1]["coalesced"],2)

    def test_metadata_projection_does_not_copy_full_layer_payload(self):
        ctx={"schema_version":"2.0","layers":{"layers":[{"name":"A","role":"r","geometry_type":"Polygon","feature_count":1,"huge_geometry":"x"*1000}]}}
        p=context_projection(ctx,"metadata")
        self.assertNotIn("huge_geometry",p["layers"]["layers"][0])

    def test_timing_breakdown_reports_dominant_stage(self):
        t=timing_breakdown({"queue":1,"gis":5,"validation":2})
        self.assertEqual(t["total"],8.0); self.assertEqual(t["dominant"],"gis")

    def test_event_ipc_requires_verified_capability(self):
        self.assertEqual(choose_ipc_mode([],"event"),"file_poll")
        self.assertEqual(choose_ipc_mode(["ipc_event_verified"],"event"),"event")

if __name__=="__main__": unittest.main()

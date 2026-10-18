import copy
import unittest

from orchestrator.batch import BatchCoordinator
from orchestrator.concurrency import ResourceClaim
from orchestrator.recipes import RecipeLibrary
from orchestrator.adapters.reasoner import ReasonerService

CTX={"available":True,"fingerprint":"f","map":{"ok":True,"crs":"EPSG:32750"},
     "dataframe":{"spatial_reference":{"wkid":32750}}}

def goal(name):
    return {
        "schema_version":"2.0","goal_type":"build_map","raw_goal":"map "+name,
        "title":name,"target_mode":"CURRENT","crs":"EPSG:32750","dry_run":True,
        "outputs":{"output_dir":"D:/out","formats":["PDF","PNG"],"dpi":400,"save_mxd":False},
    }

class BatchTests(unittest.TestCase):
    def test_disjoint_claims_share_one_wave(self):
        r=BatchCoordinator().compile(
            [goal("a"),goal("b")],[copy.deepcopy(CTX),copy.deepcopy(CTX)],
            [[ResourceClaim("mxd:a","write")],[ResourceClaim("mxd:b","write")]])
        self.assertTrue(r["ok"]); self.assertEqual(len(r["waves"]),1)

    def test_conflicting_write_claims_are_serialized(self):
        r=BatchCoordinator().compile(
            [goal("a"),goal("b")],[copy.deepcopy(CTX),copy.deepcopy(CTX)],
            [[ResourceClaim("mxd:same","write")],[ResourceClaim("mxd:same","write")]])
        self.assertTrue(r["ok"]); self.assertEqual(len(r["waves"]),2)

    def test_output_collision_blocks_batch_before_execution(self):
        g=goal("same")
        r=BatchCoordinator().compile([copy.deepcopy(g),copy.deepcopy(g)],[CTX,CTX],[[],[]])
        self.assertFalse(r["ok"]); self.assertEqual(r["errors"][0]["code"],"OUTPUT_COLLISION")

class RecipeTests(unittest.TestCase):
    def test_recipe_is_versioned_and_hashed(self):
        lib=RecipeLibrary({"arcmap_set_title","arcmap_set_map_scale"})
        entry=lib.register("admin-map","1.0.0",{"actions":[
            {"action":"arcmap_set_title","arguments":{"title":"A"}},
            {"action":"arcmap_set_map_scale","arguments":{"scale":50000}},
        ]})
        self.assertEqual(len(entry["sha256"]),64)
        self.assertEqual(lib.versions("admin-map"),["1.0.0"])

    def test_recipe_rejects_unknown_action_and_arbitrary_code(self):
        lib=RecipeLibrary({"arcmap_set_title"})
        with self.assertRaisesRegex(ValueError,"RECIPE_ACTION_FORBIDDEN"):
            lib.register("x","1.0.0",{"actions":[{"action":"unknown"}]})
        with self.assertRaisesRegex(ValueError,"ARBITRARY_CODE_FORBIDDEN"):
            lib.register("y","1.0.0",{"actions":[{"action":"arcmap_set_title","script":"evil"}]})

    def test_recipe_version_cannot_be_silently_overwritten(self):
        lib=RecipeLibrary({"arcmap_set_title"})
        recipe={"actions":[{"action":"arcmap_set_title"}]}
        lib.register("x","1.0.0",recipe)
        with self.assertRaisesRegex(ValueError,"RECIPE_VERSION_EXISTS"):
            lib.register("x","1.0.0",recipe)

class ReasonerTests(unittest.TestCase):
    def test_absent_provider_waits_for_review(self):
        r=ReasonerService(None).assess({"artifact":"a"})
        self.assertFalse(r["ok"]); self.assertEqual(r["status"],"WAITING_FOR_REVIEW")

    def test_provider_receives_explicit_timeout_and_budget(self):
        class Provider:
            def __init__(self): self.kw=None
            def assess(self,payload,**kwargs):
                self.kw=kwargs
                return {"status":"PASS","confidence":0.9,"provider_version":"p1","prompt_version":"v2"}
        p=Provider(); s=ReasonerService(p,timeout_seconds=12,budget={"max_tokens":1000})
        r=s.assess({"x":1})
        self.assertTrue(r["ok"]); self.assertEqual(p.kw["timeout_seconds"],12.0)
        self.assertEqual(p.kw["budget"]["max_tokens"],1000)

    def test_invalid_provider_result_fails_closed_to_review(self):
        class Provider:
            def assess(self,payload,**kwargs): return {"status":"MAGIC","confidence":2}
        r=ReasonerService(Provider()).assess({})
        self.assertFalse(r["ok"]); self.assertEqual(r["status"],"WAITING_FOR_REVIEW")

    def test_provider_timeout_waits_for_review(self):
        class Provider:
            def assess(self,payload,**kwargs): raise TimeoutError()
        r=ReasonerService(Provider()).assess({})
        self.assertEqual(r["errors"][0]["code"],"REASONER_TIMEOUT")

if __name__=="__main__": unittest.main()

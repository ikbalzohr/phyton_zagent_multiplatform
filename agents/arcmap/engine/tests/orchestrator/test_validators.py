import unittest

from orchestrator.validators import validate_gis, validate_layout, ValidatorRegistry, VisualReviewService

GOOD_CONTEXT={
    "layers":{"layers":[
        {"role":"batas_perusahaan","name":"BATAS","broken":False,"geometry_type":"Polygon","fields":["ID"],"feature_count":1},
        {"role":"jalan","name":"JALAN","broken":False,"geometry_type":"Polyline","fields":["NAMA"],"feature_count":10},
    ]},
    "dataframe":{"spatial_reference":{"wkid":32750}},
    "mixed_crs":False,
    "gp_subset_verified":True,
    "available_capabilities":["basic"],
}
GIS_PROFILE={
    "required_layer_roles":["batas_perusahaan","jalan"],
    "subset_verification_required":True,
    "required_capabilities":["basic"],
    "layer_rules":{
        "batas_perusahaan":{"geometry_type":"Polygon","required_fields":["ID"],"nonempty":True},
        "jalan":{"geometry_type":"Polyline","required_fields":["NAMA"],"nonempty":True},
    }
}
GOOD_LAYOUT={
    "page_width_mm":297.0,"page_height_mm":210.0,
    "elements":[
        {"role":"title","bounds_mm":[10,5,120,15]},
        {"role":"legend","bounds_mm":[230,30,50,100]},
        {"role":"map","bounds_mm":[10,25,210,170]},
    ]
}
LAYOUT_PROFILE={"orientation":"landscape","required_elements":["title","legend","map"],
                "non_overlap_roles":["title","legend","map"]}

class ValidatorsTests(unittest.TestCase):
    def test_good_fixture_passes(self):
        g=validate_gis(GOOD_CONTEXT,GIS_PROFILE)
        l=validate_layout(GOOD_LAYOUT,LAYOUT_PROFILE)
        self.assertEqual(g["status"],"PASS"); self.assertEqual(l["status"],"PASS")

    def test_missing_required_layer_is_critical_fail(self):
        ctx=dict(GOOD_CONTEXT); ctx["layers"]={"layers":[GOOD_CONTEXT["layers"]["layers"][0]]}
        r=validate_gis(ctx,GIS_PROFILE)
        self.assertEqual(r["status"],"FAIL")
        self.assertTrue(any(x["rule_id"]=="GIS_REQUIRED_LAYERS" and x["status"]=="FAIL" for x in r["results"]))

    def test_unknown_crs_fails_without_guessing(self):
        ctx={**GOOD_CONTEXT,"dataframe":{}}
        r=validate_gis(ctx,GIS_PROFILE)
        self.assertTrue(any(x["rule_id"]=="GIS_CRS_KNOWN" and x["status"]=="FAIL" for x in r["results"]))

    def test_mixed_crs_requires_verified_transformation(self):
        ctx={**GOOD_CONTEXT,"mixed_crs":True,"datum_transformation_verified":False}
        r=validate_gis(ctx,GIS_PROFILE)
        self.assertTrue(any(x["rule_id"]=="GIS_MIXED_CRS_TRANSFORM" and x["status"]=="FAIL" for x in r["results"]))
        ctx["datum_transformation_verified"]=True
        self.assertFalse(any(x["rule_id"]=="GIS_MIXED_CRS_TRANSFORM" and x["status"]=="FAIL" for x in validate_gis(ctx,GIS_PROFILE)["results"]))

    def test_layout_out_of_bounds_fails_and_offers_registered_repair(self):
        layout={**GOOD_LAYOUT,"elements":[
            {"role":"title","bounds_mm":[290,5,20,15]},
            {"role":"legend","bounds_mm":[230,30,50,100]},
            {"role":"map","bounds_mm":[10,25,210,170]},
        ]}
        r=validate_layout(layout,LAYOUT_PROFILE)
        item=next(x for x in r["results"] if x["rule_id"]=="LAYOUT_BOUNDS")
        self.assertEqual(item["status"],"FAIL"); self.assertEqual(item["permitted_repair"],"move_element_in_bounds")

    def test_registry_never_hides_gis_failure_with_good_layout(self):
        bad={**GOOD_CONTEXT,"dataframe":{}}
        report=ValidatorRegistry().validate(bad,GOOD_LAYOUT,{"gis":GIS_PROFILE,"layout":LAYOUT_PROFILE})
        self.assertEqual(report["status"],"FAIL")

class VisualTests(unittest.TestCase):
    def test_no_provider_needs_review_not_pass(self):
        r=VisualReviewService(None).review({"artifact_id":"a"})
        self.assertEqual(r["status"],"NEEDS_REVIEW")

    def test_deterministic_critical_failure_blocks_visual_provider(self):
        class Provider:
            def __init__(self): self.called=False
            def assess(self,a): self.called=True; return {"status":"PASS","results":[]}
        p=Provider()
        det={"status":"FAIL","results":[{"rule_id":"GIS_CRS","status":"FAIL","severity":"critical","expected":"known","actual":None}]}
        r=VisualReviewService(p).review({},det)
        self.assertEqual(r["status"],"FAIL"); self.assertFalse(p.called)

    def test_invalid_provider_result_fails_closed(self):
        class Provider:
            def assess(self,a): return {"status":"MAGIC"}
        r=VisualReviewService(Provider()).review({})
        self.assertEqual(r["status"],"FAIL")

if __name__=="__main__": unittest.main()

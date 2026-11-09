"""Rule precedence, hot reload, safe auto-create, and adaptive scale unit tests."""
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import patch
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "agents/arcmap/engine"))
from orchestrator.cartographic_rules import resolve_rules, CartographicRuleError
from stage2.cartographic_apply import _choose_scale, _bounds_inside, _find_main, _main_bounds, _rewrite_main_scale_label

def rule_doc(data, exceptions="Belum ada pengecualian tambahan."):
    return ("# Aturan\n\n## Pengecualian desain proyek\n" +
            exceptions + "\n\n" +
            "```zagent-cartography\n" + json.dumps(data) + "\n```\n")

class RuleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.agent = self.root / "arcmap"
        self.engine = self.agent / "engine"
        self.project = self.root / "project"
        self.engine.mkdir(parents=True)
        self.project.mkdir()
        (self.agent / "ZAGENT.md").write_text(rule_doc({
            "scale":{"mode":"auto","padding_fraction":0.12},
            "typography":{"important_min_pt":7}
        }),encoding="utf-8")

    def tearDown(self):
        self.temp.cleanup()

    def test_project_precedence_and_explicit_job_override(self):
        (self.project / "ZAGENT.md").write_text(
            rule_doc({"scale":{"padding_fraction":0.2},"area":{"layer":"KAWASAN A"}}),
            encoding="utf-8")
        a=resolve_rules(self.engine,self.project)
        self.assertEqual(a["rules"]["scale"]["padding_fraction"],0.2)
        self.assertEqual(a["rules"]["area"]["layer"],"KAWASAN A")
        self.assertEqual(a["rules"]["scale"]["mode"],"auto")
        b=resolve_rules(self.engine,self.project,scale_override=25000)
        self.assertEqual(b["rules"]["scale"]["mode"],"fixed")
        self.assertEqual(b["rules"]["scale"]["requested"],25000)
        self.assertEqual(len(b["sources"]),2)

    def test_hot_reload_on_next_job(self):
        p=self.project / "ZAGENT.md"
        p.write_text(rule_doc({"area":{"layer":"KAWASAN A"}}),encoding="utf-8")
        first=resolve_rules(self.engine,self.project)
        p.write_text(rule_doc({"area":{"layer":"KAWASAN B"}}),encoding="utf-8")
        second=resolve_rules(self.engine,self.project)
        self.assertEqual(first["rules"]["area"]["layer"],"KAWASAN A")
        self.assertEqual(second["rules"]["area"]["layer"],"KAWASAN B")
        self.assertNotEqual(first["sources"][1]["sha256"],second["sources"][1]["sha256"])

    def test_create_project_if_write_allowed(self):
        p=self.project / "ZAGENT.md"
        self.assertFalse(p.exists())
        result=resolve_rules(self.engine,self.project)
        self.assertTrue(result["project_file_created"])
        self.assertTrue(p.exists())
        again=resolve_rules(self.engine,self.project)
        self.assertFalse(again["project_file_created"])

    def test_no_create_when_read_only(self):
        p=self.project / "ZAGENT.md"
        with patch("orchestrator.cartographic_rules.os.access",return_value=False):
            result=resolve_rules(self.engine,self.project)
        self.assertFalse(p.exists())
        self.assertEqual(len(result["sources"]),1)

    def test_fail_closed_on_free_text_exception(self):
        (self.project / "ZAGENT.md").write_text(
            rule_doc({}, "- Gunakan garis biru tua untuk batas area"),encoding="utf-8")
        with self.assertRaisesRegex(CartographicRuleError,"NEEDS_INTERPRETATION"):
            resolve_rules(self.engine,self.project)

    def test_untrusted_rule_cannot_change_format_or_security(self):
        p=self.project / "ZAGENT.md"
        p.write_text(rule_doc({"format":{"dpi":200}}),encoding="utf-8")
        with self.assertRaisesRegex(CartographicRuleError,"FIXED_A4"):
            resolve_rules(self.engine,self.project)
        p.write_text(rule_doc({"allow_save":True}),encoding="utf-8")
        with self.assertRaisesRegex(CartographicRuleError,"UNSUPPORTED_RULE"):
            resolve_rules(self.engine,self.project)

    def test_missing_block_is_error(self):
        (self.project / "ZAGENT.md").write_text("No valid block",encoding="utf-8")
        with self.assertRaisesRegex(CartographicRuleError,"ONE_CARTOGRAPHY_BLOCK"):
            resolve_rules(self.engine,self.project)

    def test_main_scale_text_only_changes_main_not_inset(self):
        self.assertEqual(
            _rewrite_main_scale_label("Skala 1 : 70.000", 70000, 50000),
            "Skala 1 : 50.000")
        self.assertEqual(
            _rewrite_main_scale_label("Skala 1 : 3.500.000", 70000, 50000),
            "Skala 1 : 3.500.000")
        self.assertEqual(
            _rewrite_main_scale_label("Skala 1 : 23.000.000", 70000, 50000),
            "Skala 1 : 23.000.000")
        self.assertEqual(
            _rewrite_main_scale_label("Some text", 70000, 50000),
            "Some text")

    def test_layer_display_extent_is_not_confused_with_native_source_extent(self):
        # ArcPy Describe(layer) is mapped into data-frame UTM coordinates
        # although the layer source is really EPSG:3857.
        layer=NS(name="PT BUOL AGRI LESTARI",isGroupLayer=False,visible=True,
                 dataSource=r"C:\data\activity.shp",
                 supports=lambda key: key=="DATASOURCE")
        displayed=NS(shapeType="Polygon",spatialReference=NS(name="Web_Mercator"),
                     extent=NS(XMin=322574,YMin=116866,XMax=328235,YMax=123828))
        native=NS(shapeType="Polygon",spatialReference=NS(name="Web_Mercator"),
                  extent=NS(XMin=13514793,YMin=117664,XMax=13520452,YMax=124671),
                  fields=[])
        gis=NS(mapping=NS(ListLayers=lambda m,w,f:[layer]),
               Describe=lambda subject: native if isinstance(subject,str) else displayed)
        result_layer,result_desc=_find_main(None,None,{"layer":layer.name,"dataset":"activity.shp"},gis)
        self.assertIs(result_layer,layer)
        self.assertIs(result_desc,native)
        self.assertNotEqual(result_desc.extent.XMin,displayed.extent.XMin)

    def test_bad_crs_projection_fails_instead_of_assuming_coordinates(self):
        frame=NS(spatialReference=NS(name="WGS_1984_UTM_Zone_51N"))
        source=NS(spatialReference=NS(name="WGS_1984_Web_Mercator_Auxiliary_Sphere"),
                  extent=NS(XMin=322000,YMin=115000,XMax=329000,YMax=125000))
        geom=NS(projectAs=lambda sr:NS(firstPoint=None))
        gis=NS(Point=lambda x,y:None,PointGeometry=lambda p,sr:geom)
        with self.assertRaisesRegex(ValueError,"DATASET_CRS_METADATA_INCONSISTENT"):
            _main_bounds(source,frame,gis)

    def test_protected_reference_root_rejected(self):
        bad=self.root / "Contoh Layout"
        bad.mkdir()
        with self.assertRaisesRegex(CartographicRuleError,"PROTECTED_REFERENCE"):
            resolve_rules(self.engine,bad)

    def test_scale_auto_smallest_standard_that_fits(self):
        df=NS(name="Layers",spatialReference=NS(type="Projected",metersPerUnit=1.0),
              extent=NS(XMin=0,YMin=0,XMax=500,YMax=500),scale=70000)
        e=NS(name="Layers",elementWidth=19.454,elementHeight=19.399)
        fake=NS(mapping=NS(ListLayoutElements=lambda m,kind:[e]),
                Extent=lambda a,b,c,d:NS(XMin=a,YMin=b,XMax=c,YMax=d))
        mxd=NS(pageSize=NS(width=29.6968927,height=20.9973753))
        policy={"scale":{"mode":"auto","padding_fraction":0.12,
                         "denominators":[1000,2500,5000,10000,25000,50000]}}
        chosen,meta=_choose_scale(mxd,df,(0,0,900,800),policy,fake)
        self.assertEqual(chosen,10000)
        self.assertEqual(meta["mode"],"auto")
        self.assertTrue(_bounds_inside(df.extent,(0,0,900,800),0.12))

if __name__ == "__main__":
    unittest.main()

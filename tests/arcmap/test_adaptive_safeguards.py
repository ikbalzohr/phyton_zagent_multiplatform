"""Regression tests for root-level MXD output and inset isolation."""
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace as NS

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "agents/arcmap/engine"))
from stage2.adaptive_safeguards import (
    unused_output_stem, keep_only_inset_basemaps, is_inset_raster
)


class Layer:
    def __init__(self, name, source, group=False, visible=True):
        self.name = name
        self.dataSource = source
        self.isGroupLayer = group
        self.visible = visible

    def supports(self, field):
        return field == "DATASOURCE"


class InsetSafeguardsTests(unittest.TestCase):
    def test_output_basename_matches_all_formats_without_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            (p / "PETA.mxd").write_bytes(b"original")
            self.assertEqual(unused_output_stem("PETA", tmp), "PETA_v2")
            self.assertEqual((p / "PETA.mxd").read_bytes(), b"original")
            (p / "PETA_v2.mxd").write_bytes(b"older-result")
            self.assertEqual(unused_output_stem("PETA", tmp), "PETA_v3")

    def test_invalid_output_name_does_not_escape_project(self):
        with tempfile.TemporaryDirectory() as tmp:
            for stem in ("", "../PETA", "a/b", ".."):
                with self.assertRaises(ValueError):
                    unused_output_stem(stem, tmp)

    def fake(self, layers1, layers2):
        main = NS(name="Layers", layers=[Layer("Area", "site.shp")])
        a = NS(name="Inset Buol", layers=layers1)
        b = NS(name="Inset Sulteng", layers=layers2)
        mapping = NS(
            ListDataFrames=lambda mxd: [main, a, b],
            ListLayers=lambda mxd, pattern, frame: list(frame.layers),
            RemoveLayer=lambda frame, lyr: frame.layers.remove(lyr))
        return NS(mapping=mapping), (main, a, b)

    def test_only_one_distinct_raster_remains_in_each_inset(self):
        buol = Layer("INSET_BUOL", r"C:\gis\INSET_BUOL_GE_Z12.ecw", visible=False)
        sulteng = Layer("INSET_SULTENG", r"C:\gis\INSET_SULTENG_Z10.ecw")
        gis, frames = self.fake(
            [Layer("lokasi", "area.shp"), buol],
            [Layer("koordinat", "point.shp"), sulteng])
        result = keep_only_inset_basemaps(None, "Layers", gis)
        self.assertEqual(len(result), 2)
        self.assertEqual(frames[1].layers, [buol])
        self.assertEqual(frames[2].layers, [sulteng])
        self.assertTrue(buol.visible)
        self.assertTrue(all(is_inset_raster(r.layers[0]) for r in frames[1:]))

    def test_ambiguous_inset_raster_fails_closed(self):
        l1 = Layer("A", r"C:\gis\INSET_A.ecw")
        l2 = Layer("B", r"C:\gis\INSET_B.ecw")
        gis, _ = self.fake([l1, l2], [Layer("C", r"C:\gis\INSET_C.ecw")])
        with self.assertRaisesRegex(ValueError, "INSET_BASEMAP_NOT_UNIQUE"):
            keep_only_inset_basemaps(None, "Layers", gis)

    def test_reused_inset_raster_fails_closed(self):
        same = r"C:\gis\INSET_A.ecw"
        gis, _ = self.fake([Layer("A", same)], [Layer("A", same)])
        with self.assertRaisesRegex(ValueError, "INSET_BASEMAP_REUSED"):
            keep_only_inset_basemaps(None, "Layers", gis)

    def test_missing_second_inset_fails(self):
        gis, _ = self.fake([Layer("A", r"C:\gis\INSET_A.ecw")],
                           [Layer("Not raster", "site.shp")])
        with self.assertRaisesRegex(ValueError, "INSET_BASEMAP_NOT_UNIQUE"):
            keep_only_inset_basemaps(None, "Layers", gis)


if __name__ == "__main__":
    unittest.main()

from stage2.rgb_composite import raster_band_count, request_rgb_composite


class RGBCompositeTests(unittest.TestCase):
    def test_rgb_3band_preserves_add_data_default_renderer(self):
        original = Layer("RGB original", r"C:\gis\BASEMAP_TEST.ecw")
        original.isRasterLayer = True
        frame = NS(name="Layers", layers=[original])
        calls = []
        gis = NS(
            Raster=lambda path: NS(bandCount=3),
            MakeRasterLayer_management=lambda *args: calls.append(("make", args)),
            mapping=NS(
                ListDataFrames=lambda mxd: [frame],
                ListLayers=lambda mxd, name, df: df.layers,
                UpdateLayer=lambda *args: calls.append(("update", args))))
        result = request_rgb_composite(None, gis)
        self.assertEqual(result[0]["band_count"], 3)
        self.assertEqual(result[0]["strategy"], "PRESERVE_ARCMAP_ADD_DATA_DEFAULT")
        self.assertEqual(result[0]["renderer_readback"], "PENDING_ARCMAP_VISUAL_QA")
        self.assertEqual(calls, [])
        self.assertEqual(original.dataSource, r"C:\gis\BASEMAP_TEST.ecw")

    def test_single_band_cannot_claim_rgb(self):
        raster = Layer("one band", r"C:\gis\INSET_TEST.ecw")
        raster.isRasterLayer = True
        frame = NS(name="Inset", layers=[raster])
        gis = NS(Raster=lambda path: NS(bandCount=1),
                 mapping=NS(ListDataFrames=lambda mxd: [frame],
                            ListLayers=lambda mxd, pattern, df: df.layers))
        with self.assertRaisesRegex(ValueError, "RGB_NEEDS_VALIDATED_BAND_MAPPING"):
            request_rgb_composite(None, gis)

"""Unit doubles for ArcMap Python 2.7 polygon reader/CRS preflight (NOT RUN)."""
import types
import unittest

from test_smart_corner_bridge_safety import _load_bridge


class FakeCursor:
    def __init__(self, rows):
        self.rows = rows

    def __enter__(self):
        return iter(self.rows)

    def __exit__(self, exc_type, exc, tb):
        return False


class FakePolygon:
    def __init__(self, points, sr, part_count=1):
        self.points = points
        self.spatialReference = sr
        self.partCount = part_count
        self.isMultipart = part_count > 1

    def getPart(self, number):
        return [None if pt is None else types.SimpleNamespace(X=pt[0], Y=pt[1])
                for pt in self.points]


class SmartCornerArcPyReaderTests(unittest.TestCase):
    def setUp(self):
        self.module, self.arcpy = _load_bridge()
        self.context = {"source_path": r"D:\unit\source.shp"}
        self.sr = types.SimpleNamespace(
            type="Projected", factoryCode=32651,
            name="WGS_1984_UTM_Zone_51N", metersPerUnit=1,
            linearUnitName="Meter"
        )
        self.points = [(0, 0), (10, 0), (10, 10), (0, 10), (0, 0)]

    def set_rows(self, rows):
        self.arcpy.da.SearchCursor.side_effect = lambda *args: FakeCursor(rows)

    def test_one_polygon_reads_exact_source_vertices(self):
        self.set_rows([(7, FakePolygon(self.points, self.sr))])
        result = self.module._geometry({}, self.context)
        self.assertEqual(7, result["feature_oid"])
        self.assertEqual("projected_linear_Meter",
                         result["metric_crs"])
        self.assertEqual(5, len(result["vertices"]))
        self.assertEqual(self.points[2][0], result["vertices"][2]["x"])
        self.assertEqual(self.points[2][1], result["vertices"][2]["metric_y"])

    def test_two_polygon_features_require_selector(self):
        self.set_rows([(1, FakePolygon(self.points, self.sr)),
                       (2, FakePolygon(self.points, self.sr))])
        with self.assertRaises(self.module.SmartCornerError) as c:
            self.module._geometry({}, self.context)
        self.assertEqual("FEATURE_SELECTION_REQUIRED", c.exception.code)

    def test_selected_oid_reads_only_one_polygon(self):
        self.set_rows([(1, FakePolygon(self.points, self.sr)),
                       (2, FakePolygon(self.points, self.sr))])
        result = self.module._geometry({"feature_oid": 2}, self.context)
        self.assertEqual(2, result["feature_oid"])

    def test_holes_fail_closed(self):
        hole = self.points[:2] + [None] + self.points[2:]
        self.set_rows([(1, FakePolygon(hole, self.sr))])
        with self.assertRaises(self.module.SmartCornerError) as c:
            self.module._geometry({}, self.context)
        self.assertEqual("HOLE_REVIEW_REQUIRED", c.exception.code)

    def test_multipart_fail_closed(self):
        self.set_rows([(1, FakePolygon(self.points, self.sr, part_count=2))])
        with self.assertRaises(self.module.SmartCornerError) as c:
            self.module._geometry({}, self.context)
        self.assertEqual("MULTIPART_REVIEW_REQUIRED", c.exception.code)

    def test_unknown_crs_fail_closed(self):
        sr = types.SimpleNamespace(type="Unknown", factoryCode=0,
                                   linearUnitName="", metersPerUnit=0)
        self.set_rows([(1, FakePolygon(self.points, sr))])
        with self.assertRaises(self.module.SmartCornerError) as c:
            self.module._geometry({}, self.context)
        self.assertEqual("INVALID_CRS", c.exception.code)

    def test_projected_feet_are_scaled_for_metric_analysis(self):
        feet = types.SimpleNamespace(type="Projected", factoryCode=26915,
                                     name="UnitFeet", metersPerUnit=0.3048,
                                     linearUnitName="Foot")
        self.set_rows([(1, FakePolygon(self.points, feet))])
        result = self.module._geometry({}, self.context)
        self.assertAlmostEqual(3.048, result["vertices"][1]["metric_x"])
        self.assertEqual(10, result["vertices"][1]["x"])

    def test_non_wgs84_geographic_crs_fails_closed(self):
        sr = types.SimpleNamespace(type="Geographic", factoryCode=4269,
                                   name="NAD83")
        self.set_rows([(1, FakePolygon(self.points, sr))])
        with self.assertRaises(self.module.SmartCornerError) as c:
            self.module._geometry({}, self.context)
        self.assertEqual("INVALID_CRS", c.exception.code)


if __name__ == "__main__":
    unittest.main()

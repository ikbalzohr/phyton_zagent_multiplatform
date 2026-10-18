"""Mock-only behavioral unit tests for ARC-05..ARC-10.

All ArcMap and network calls are isolated; does not start ArcMap or request URLs.
"""
import io
import os
import pathlib
import tempfile
import types
import unittest
from unittest import mock

from test_arc05_10_source_units import load_feature


class LabelPresetBehaviorTests(unittest.TestCase):
    def setUp(self):
        self.m = load_feature("native_label_preset")
        self.df = types.SimpleNamespace(name="Layers")
        self.layer = types.SimpleNamespace(name="Tapak Proyek")
        self.m.find_layer = mock.Mock(return_value=[(self.df, self.layer)])
        self.m.get_mxd = mock.Mock(return_value=object())

    def test_unknown_preset_rejected(self):
        with self.assertRaises(ValueError):
            self.m.native_label_preset({"layer_name": "Tapak Proyek",
                                        "preset": "NOT_A_STYLE"})

    def test_invalid_font_size_rejected(self):
        with self.assertRaises(ValueError):
            self.m.native_label_preset({"layer_name": "Tapak Proyek",
                                        "preset": "FONT_2", "size": 0})

    def test_ambiguous_layer_rejected(self):
        self.m.find_layer.return_value = [(self.df, self.layer), (self.df, self.layer)]
        with self.assertRaises(RuntimeError):
            self.m.native_label_preset({"layer_name": "Tapak Proyek"})

    def test_apply_preset_to_single_class(self):
        label = mock.Mock()
        label.Symbol.Size = 1.0
        geo = mock.Mock()
        collection = geo.AnnotationProperties.QueryInterface.return_value
        collection.Count = 1
        collection.QueryItem.return_value = (mock.Mock(), 7)
        collection.QueryItem.return_value[0].QueryInterface.return_value = label
        carto = mock.Mock()
        self.m._geo = mock.Mock(return_value=(geo, carto))
        self.m.arcpy.RefreshActiveView = mock.Mock()
        response = self.m.native_label_preset({
            "layer_name": "Tapak Proyek", "size": 11,
            "font_name": "Arial", "preset": "FONT_2"})
        self.assertTrue(response["ok"])
        self.assertEqual(label.Symbol.Size, 11.0)
        collection.Replace.assert_called_once()
        self.assertEqual(geo.DisplayAnnotation, True)


class ScaleBarBehaviorTests(unittest.TestCase):
    def setUp(self):
        self.m = load_feature("native_scale_bar")
        self.bar = types.SimpleNamespace(
            Units=10, UnitLabel="km", Division=2.5,
            Divisions=4, Subdivisions=2)
        self.m._scale_bars = mock.Mock(return_value=(
            mock.Mock(), [("Scalebar", self.bar)]))
        self.m.arcpy.RefreshActiveView = mock.Mock()

    def test_preserve_physical_distance_km_to_m(self):
        result = self.m.set_native_scale_bar({
            "element_name": "Scalebar", "units": "METERS",
            "preserve_distance": True})
        self.assertTrue(result["ok"])
        self.assertEqual(result["before"]["division"], 2.5)
        self.assertEqual(self.bar.Division, 2500)
        self.assertEqual(self.bar.UnitLabel, "m")

    def test_preserve_distance_m_to_km(self):
        self.bar.Units = 9
        self.bar.Division = 1200
        self.bar.UnitLabel = "m"
        self.m.set_native_scale_bar({
            "element_name": "Scalebar", "units": "KILOMETERS"})
        self.assertAlmostEqual(self.bar.Division, 1.2)

    def test_dont_convert_division_when_disabled(self):
        self.m.set_native_scale_bar({
            "element_name": "Scalebar", "units": "METERS",
            "preserve_distance": False})
        self.assertEqual(self.bar.Division, 2.5)

    def test_duplicate_named_scale_bars_rejected(self):
        self.m._scale_bars.return_value = (
            mock.Mock(), [("Scalebar", self.bar), ("Scalebar", self.bar)])
        with self.assertRaises(RuntimeError):
            self.m.set_native_scale_bar({
                "element_name": "Scalebar", "units": "METERS"})

    def test_missing_element_name_rejected(self):
        with self.assertRaises(ValueError):
            self.m.set_native_scale_bar({"units": "METERS"})

    def test_unsupported_units_rejected(self):
        with self.assertRaises(ValueError):
            self.m.set_native_scale_bar({
                "element_name": "Scalebar", "units": "DEGREES"})


class MapserverDescriptorBehaviorTests(unittest.TestCase):
    def setUp(self):
        self.m = load_feature("gis_server_connector")
        self.url = "https://example.org/arcgis/rest/services/A/MapServer"

    def response(self, content, url=None):
        obj = mock.Mock()
        obj.read.return_value = content
        obj.geturl.return_value = url or self.url + "?f=lyr"
        return obj

    def test_descriptor_binary_received(self):
        with mock.patch.object(self.m.urllib2, "urlopen",
                               return_value=self.response(b"\x00binary")):
            self.assertEqual(self.m.layer_descriptor(self.url), b"\x00binary")

    def test_html_error_is_not_layer(self):
        with mock.patch.object(self.m.urllib2, "urlopen",
                               return_value=self.response(b"<html>bad</html>")):
            with self.assertRaises(RuntimeError):
                self.m.layer_descriptor(self.url)

    def test_insecure_redirect_rejected(self):
        with mock.patch.object(
                self.m.urllib2, "urlopen",
                return_value=self.response(b"abc", "http://example.org/lyr")):
            with self.assertRaises(RuntimeError):
                self.m.layer_descriptor(self.url)

    def test_oversized_descriptor_rejected(self):
        with mock.patch.object(
                self.m.urllib2, "urlopen",
                return_value=self.response(b"12345")):
            with self.assertRaises(RuntimeError):
                self.m.layer_descriptor(self.url, limit=4)


class GeometryBehaviorTests(unittest.TestCase):
    def setUp(self):
        self.m = load_feature("calculate_geometry")
        self.out_sr = mock.Mock()

    def test_valid_point_projection(self):
        geometry = mock.Mock(type="point")
        geometry.spatialReference.name = "WGS_1984"
        geometry.projectAs.return_value.type = "point"
        geometry.projectAs.return_value.firstPoint.X = 121.22463
        geometry.projectAs.return_value.firstPoint.Y = 1.077135
        result = self.m.safe_xy(geometry, self.out_sr)
        self.assertEqual(result, (121.22463, 1.077135))
        geometry.projectAs.assert_called_once_with(self.out_sr)

    def test_nan_coordinate_rejected(self):
        geometry = mock.Mock(type="point")
        geometry.spatialReference.name = "WGS_1984"
        geometry.projectAs.return_value.type = "point"
        geometry.projectAs.return_value.firstPoint.X = float("nan")
        geometry.projectAs.return_value.firstPoint.Y = 1
        with self.assertRaises(ValueError):
            self.m.safe_xy(geometry, self.out_sr)

    def test_null_geometry(self):
        self.assertIsNone(self.m.safe_xy(None, self.out_sr))


class CoordinateImportBehaviorTests(unittest.TestCase):
    def setUp(self):
        self.m = load_feature("smart_coordinate_importer")

    def test_csv_rows_with_headers(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "coordinate.csv")
            with open(path, "w", encoding="utf-8", newline="") as f:
                f.write("X,Y,LABEL\n121.224630,1.077135,PT-1\n")
            rows = self.m._csv_points(path, "X", "Y", "LABEL", ",", 100)
            self.assertEqual(rows, [(121.22463, 1.077135, "PT-1")])

    def test_csv_row_limit_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "coordinate.csv")
            with open(path, "w", encoding="utf-8", newline="") as f:
                f.write("X,Y\n121,1\n122,2\n")
            with self.assertRaises(ValueError):
                self.m._csv_points(path, "X", "Y", "LABEL", ",", 1)

    def test_missing_csv_columns_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "coordinate.csv")
            with open(path, "w", encoding="utf-8", newline="") as f:
                f.write("LAT,LON\n1,121\n")
            with self.assertRaises(ValueError):
                self.m._csv_points(path, "X", "Y", "LABEL", ",", 100)


if __name__ == "__main__":
    unittest.main()
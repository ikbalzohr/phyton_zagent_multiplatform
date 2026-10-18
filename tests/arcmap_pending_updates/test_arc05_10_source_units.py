"""ARC-05..ARC-10 deferred unit tests (no ArcMap instance required)."""
import ast
import importlib.util
import pathlib
import sys
import types
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[2]
ENGINE = ROOT / "agents" / "arcmap" / "engine"
FEATURES = ENGINE / "arcmap_bridge" / "features"


def load_feature(name):
    """Load isolated feature functions with inert fake ArcPy imports."""
    arcpy = types.ModuleType("arcpy")
    core = types.ModuleType("core")
    core.__path__ = []
    registry = types.ModuleType("core.registry")
    registry.action = lambda name: (lambda func: func)
    current_map = types.ModuleType("core.current_map")
    for attr in ("get_mxd", "find_layer", "safe_layer_source", "get_dataframe"):
        setattr(current_map, attr, mock.Mock())
    path_guard = types.ModuleType("core.path_guard")
    path_guard.guard_manual_write = mock.Mock(return_value=None)
    safety = types.ModuleType("core.safety")
    for attr in ("require_live_write", "require_geoprocessing", "require_destructive"):
        setattr(safety, attr, mock.Mock(return_value=None))
    features = types.ModuleType("features")
    features.__path__ = []
    native = types.ModuleType("features.native_layer_properties")
    native._geo = mock.Mock()
    stage3 = types.ModuleType("stage3")
    stage3.__path__ = []
    stage3_bridge = types.ModuleType("stage3.bridge")
    stage3.bridge = stage3_bridge
    mapping = {"arcpy": arcpy, "core": core, "core.registry": registry,
               "core.current_map": current_map,
               "core.path_guard": path_guard, "core.safety": safety,
               "features": features, "features.native_layer_properties": native,
               "stage3": stage3, "stage3.bridge": stage3_bridge}
    # Bridge target uses Python 2 urllib2/urlparse; adapters are inert here.
    import urllib.request
    import urllib.parse
    mapping["urllib2"] = urllib.request
    mapping["urlparse"] = urllib.parse
    spec = importlib.util.spec_from_file_location(
        "arc05_10_" + name, FEATURES / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    with mock.patch.dict(sys.modules, mapping):
        spec.loader.exec_module(module)
    return module


class CoordinateValidationTests(unittest.TestCase):
    def test_decimal_and_dms(self):
        m = load_feature("smart_coordinate_importer")
        self.assertAlmostEqual(m.parse_coordinate("121,224630", "x"), 121.224630)
        self.assertAlmostEqual(m.parse_coordinate("1 4 30 N", "y"), 1.075)
        self.assertAlmostEqual(m.parse_coordinate("1 4 30 S", "y"), -1.075)
        self.assertEqual(m.parse_coordinate(0, "x"), 0)

    def test_hemisphere_and_bounds_of_dms(self):
        m = load_feature("smart_coordinate_importer")
        with self.assertRaises(ValueError):
            m.parse_coordinate("121 E", "y")
        with self.assertRaises(ValueError):
            m.parse_coordinate("1 62 15 N", "y")
        with self.assertRaises(ValueError):
            m.parse_coordinate("", "x")

    def test_mapserver_url_allowlist(self):
        m = load_feature("gis_server_connector")
        self.assertEqual(
            m.normalize_service_url(
                "https://sample.example.org/arcgis/rest/services/X/MapServer"),
            "https://sample.example.org/arcgis/rest/services/X/MapServer")
        for url in ("http://example.com/MapServer",
                    "https://localhost/arcgis/MapServer",
                    "https://example.com/MapServer?token=secret",
                    "https://example.com/FeatureServer",
                    "https://example.com/MapServer/0"):
            with self.assertRaises(ValueError):
                m.normalize_service_url(url)

    def test_xy_field_validation_and_unknown_crs(self):
        m = load_feature("calculate_geometry")
        self.assertEqual(m.validate_field_names("X_DD", "Y_DD"), ("X_DD", "Y_DD"))
        with self.assertRaises(ValueError):
            m.validate_field_names("X_DD", "x_dd")
        shape = mock.Mock()
        shape.spatialReference.name = "Unknown"
        with self.assertRaises(ValueError):
            m.safe_xy(shape, mock.Mock())

    def test_dataset_mutations_require_confirmation(self):
        geometry = load_feature("calculate_geometry")
        importer = load_feature("smart_coordinate_importer")
        self.assertEqual(
            geometry.calculate_geometry_xy({})["code"],
            "DATASET_WRITE_CONFIRMATION_REQUIRED")
        self.assertEqual(
            importer.import_coordinates_to_shp({})["code"],
            "CREATE_SHP_CONFIRMATION_REQUIRED")

    def test_label_presets_and_scale_unit_conversion_factors(self):
        label = load_feature("native_label_preset")
        scale = load_feature("native_scale_bar")
        self.assertIn("FONT_2", label.PRESETS)
        self.assertEqual(scale.UNITS["METERS"][0], 9)
        self.assertEqual(scale.UNITS["KILOMETERS"][0], 10)


class SourceWiringTests(unittest.TestCase):
    def test_all_bridge_actions_declared(self):
        expected = {
            "native_label_preset.py": "native_label_preset",
            "gis_server_connector.py": "connect_gis_mapserver",
            "native_scale_bar.py": "set_native_scale_bar",
            "calculate_geometry.py": "calculate_geometry_xy",
            "smart_coordinate_importer.py": "import_coordinates_to_shp",
            "concurrent_edit.py": "edit_guard_acquire",
        }
        for filename, action_name in expected.items():
            with self.subTest(filename=filename):
                path = FEATURES / filename
                source = path.read_text(encoding="utf-8")
                self.assertIn('@action("' + action_name + '")', source)
                ast.parse(source)

    def test_mcp_registration_and_dispatcher_integration(self):
        mcp = (ENGINE / "mcp_server" / "tools" / "arc_backlog.py").read_text()
        server = (ENGINE / "mcp_server" / "server.py").read_text()
        dispatcher = (ENGINE / "arcmap_bridge" / "core" /
                      "dispatcher.py").read_text()
        self.assertEqual(mcp.count("@mcp.tool()"), 9)
        self.assertIn("arc_backlog,", server)
        self.assertIn("concurrent_edit_guard.reject_mutation(command)", dispatcher)
        for module in ("native_label_preset", "gis_server_connector",
                       "native_scale_bar", "calculate_geometry",
                       "smart_coordinate_importer", "concurrent_edit"):
            self.assertIn("from features import " + module, dispatcher)


if __name__ == "__main__":
    unittest.main()

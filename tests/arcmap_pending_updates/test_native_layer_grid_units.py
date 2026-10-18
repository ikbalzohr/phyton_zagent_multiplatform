"""ArcObjects-free native Layer Properties and grid unit doubles.

Tests are authored but must NOT be run until specifically authorized.
"""
import importlib.util
import os
import sys
import types
import unittest
from unittest.mock import MagicMock, patch

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
_BRIDGE = os.path.join(_ROOT, "agents", "arcmap", "engine", "arcmap_bridge")
if _BRIDGE not in sys.path:
    sys.path.insert(0, _BRIDGE)


def module_under_stubs(name):
    arcpy = types.ModuleType("arcpy")
    arcpy.RefreshTOC = MagicMock()
    arcpy.RefreshActiveView = MagicMock()
    safety = types.ModuleType("core.safety")
    safety.require_live_write = lambda: None
    mapping = types.ModuleType("core.current_map")
    mapping.get_mxd = MagicMock()
    mapping.get_dataframe = MagicMock()
    mapping.find_layer = MagicMock()
    mapping.safe_layer_source = MagicMock(return_value="D:/test/source.shp")
    stage3 = types.ModuleType("stage3")
    bridge = types.ModuleType("stage3.bridge")
    stage3.bridge = bridge
    features = types.ModuleType("features")
    cartography = types.ModuleType("features.cartography")
    cartography.capture_layer_style = MagicMock(return_value={"ok": True, "token": "unit-token"})
    cartography.restore_layer_style = MagicMock(return_value={"ok": True})
    features.cartography = cartography
    mocks = {
        "arcpy": arcpy, "core.safety": safety, "core.current_map": mapping,
        "stage3": stage3, "stage3.bridge": bridge,
        "features": features, "features.cartography": cartography,
    }
    path = os.path.join(_BRIDGE, "features", name + ".py")
    with patch.dict(sys.modules, mocks):
        spec = importlib.util.spec_from_file_location("unit_" + name, path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    return module, mocks


class FakeUniqueRenderer:
    FieldCount = 1
    UseDefaultSymbol = False

    def __init__(self, values):
        self.values = list(values)
        self.labels = {v: v for v in values}
        self.fields = ["KELAS"]

    def get_Field(self, index):
        return self.fields[index]

    def get_Value(self, index):
        return self.values[index]

    def get_Label(self, name):
        return self.labels[name]

    @property
    def ValueCount(self):
        return len(self.values)


class NativeLayerPropertiesUnitTests(unittest.TestCase):
    def setUp(self):
        self.module, self.mocks = module_under_stubs("native_layer_properties")

    def test_read_two_native_unique_categories_and_other_values_false(self):
        renderer = FakeUniqueRenderer(["PIPPIB PRIMER", "NON-PIPPIB"])
        fake_layer = types.SimpleNamespace(symbologyType="OTHER")
        with patch.object(self.module, "_unique", return_value=(None, renderer)):
            result = self.module._renderer_state(fake_layer)
        self.assertEqual("UNIQUE_VALUES", result["renderer_type"])
        self.assertEqual("KELAS", result["value_field"])
        self.assertFalse(result["show_other_values"])
        self.assertEqual(["PIPPIB PRIMER", "NON-PIPPIB"],
                         [x["value"] for x in result["categories"]])

    def test_unique_category_api_supports_labels(self):
        renderer = FakeUniqueRenderer(["CLASS A", "CLASS B"])
        self.assertEqual("CLASS A", self.module._indexed_get(renderer, "Value", 0))
        self.assertEqual("CLASS B", self.module._indexed_get(renderer, "Value", 1))
        self.assertEqual("CLASS A", self.module._indexed_get(renderer, "Label", "CLASS A"))

    def test_properties_write_rejects_unsupported_tabs(self):
        result = self.module.set_native_layer_properties({
            "layer_name": "Target", "properties": {"joins_relates": ["other"]}})
        self.assertFalse(result["ok"])
        self.assertFalse(result["saved"])

    def test_properties_write_requires_explicit_fields(self):
        result = self.module.set_native_layer_properties({
            "layer_name": "Target", "properties": {}})
        self.assertFalse(result["ok"])

    def test_renderer_missing_field_is_rejected_before_mutation(self):
        with patch.object(self.module, "_single", return_value=(None, None)):
            with patch.object(self.module, "_scan_values", side_effect=ValueError("Field not found")):
                result = self.module._with_rollback(
                    {"layer_name": "Target"},
                    lambda: self.module._install_unique(
                        {"layer_name": "Target", "field_name": "MISSING"}))
        self.assertFalse(result["ok"])
        self.assertEqual({"ok": True}, result["rollback"])
        self.mocks["features.cartography"].restore_layer_style.assert_called_once()

    def test_renderer_snapshot_failure_blocks_mutation(self):
        self.mocks["features.cartography"].capture_layer_style.return_value = {
            "ok": False, "error": "snapshot unavailable"}
        with self.assertRaises(RuntimeError):
            self.module.set_native_unique_values_renderer(
                {"layer_name": "Target", "field_name": "KELAS"})


class FakeGrid:
    def __init__(self, name, interval=1/60):
        self.Name = name
        self.Visible = True
        self.XIntervalSize = interval
        self.YIntervalSize = interval
        self.TickLength = 1
        self.SubTickCount = 2
        self.SubTickLength = 0.4
        self._label_sides = (True, True, True, True)
        self._tick_sides = (True, False, True, False)
        self._sub_sides = (False, False, False, False)
        self.LabelFormat = types.SimpleNamespace(LabelOffset=2.0)

    def QueryInterface(self, interface):
        return self

    def SetLabelVisibility(self, left, top, right, bottom):
        self._label_sides = (left, top, right, bottom)

    def QueryLabelVisibility(self):
        return self._label_sides

    def SetTickVisibility(self, left, top, right, bottom):
        self._tick_sides = (left, top, right, bottom)

    def QueryTickVisibility(self):
        return self._tick_sides

    def SetSubTickVisibility(self, left, top, right, bottom):
        self._sub_sides = (left, top, right, bottom)

    def QuerySubTickVisibility(self):
        return self._sub_sides


class FakeGrids:
    def __init__(self, grids):
        self.members = list(grids)

    @property
    def MapGridCount(self):
        return len(self.members)

    def get_MapGrid(self, index):
        return self.members[index]


class NativeGridUnitTests(unittest.TestCase):
    def setUp(self):
        self.module, self.mocks = module_under_stubs("native_grids")
        self.grid = FakeGrid("Existing Graticule")
        self.other = FakeGrid("Other Grid")
        self.grids = FakeGrids([self.grid, self.other])
        self.carto = types.SimpleNamespace(IMeasuredGrid=object(), IGraticule=object())
        self.doc = MagicMock()
        self.mxd = types.SimpleNamespace(filePath="D:/unit/current.mxd")
        self.df = types.SimpleNamespace(name="Layers")
        self.frame_patch = patch.object(self.module, "_frame_and_grids",
                                        return_value=(self.mxd, self.df, self.doc,
                                                      self.carto, self.grids, "unit"))
        self.frame_patch.start()
        self.addCleanup(self.frame_patch.stop)
        self.refresh_patch = patch.object(self.module, "_refresh")
        self.refresh_patch.start()
        self.addCleanup(self.refresh_patch.stop)

    def test_grid_list_is_nonmutating(self):
        before = len(self.grids.members)
        r = self.module.list_native_grids({})
        self.assertTrue(r["ok"])
        self.assertEqual(2, len(r["grids"]))
        self.assertEqual(before, len(self.grids.members))
        self.assertFalse(r["saved"])

    def test_existing_graticule_interval_changes_without_new_grid(self):
        result = self.module.set_native_grid_properties({
            "grid_name": "Existing Graticule",
            "properties": {"x_interval": 1/120, "y_interval": 1/120}})
        self.assertTrue(result["ok"])
        self.assertEqual(2, len(self.grids.members))
        self.assertIs(self.grid, self.grids.members[0])
        self.assertAlmostEqual(1/120, self.grid.XIntervalSize)
        self.assertAlmostEqual(1/120, self.grid.YIntervalSize)
        self.assertIn("grid_snapshot_token", result)
        self.assertFalse(result["saved"])

    def test_grid_requires_explicit_name_or_index(self):
        with self.assertRaises(ValueError):
            self.module.get_native_grid_properties({})

    def test_duplicate_grid_names_rejected(self):
        self.other.Name = self.grid.Name
        with self.assertRaises(RuntimeError):
            self.module.get_native_grid_properties({"grid_name": self.grid.Name})

    def test_label_and_tick_side_order_is_preserved(self):
        result = self.module.set_native_grid_properties({
            "grid_name": "Existing Graticule",
            "properties": {
                "label_sides": {"left": True, "top": False, "right": True, "bottom": False},
                "tick_sides": {"left": False, "top": True, "right": False, "bottom": True},
                "label_offset": 3.0}})
        self.assertTrue(result["ok"])
        self.assertEqual((True, False, True, False), self.grid._label_sides)
        self.assertEqual((False, True, False, True), self.grid._tick_sides)
        self.assertEqual(3.0, self.grid.LabelFormat.LabelOffset)

    def test_negative_interval_never_applied(self):
        result = self.module.set_native_grid_properties({
            "grid_name": "Existing Graticule",
            "properties": {"x_interval": -1.0}})
        self.assertFalse(result["ok"])
        self.assertAlmostEqual(1/60, self.grid.XIntervalSize)

    def test_remove_without_confirm_does_not_touch_grid(self):
        response = self.module.remove_native_grid({"grid_name": self.grid.Name})
        self.assertFalse(response["ok"])
        self.assertEqual(2, len(self.grids.members))


if __name__ == "__main__":
    unittest.main()

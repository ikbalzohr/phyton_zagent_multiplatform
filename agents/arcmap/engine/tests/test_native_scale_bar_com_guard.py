"""Isolated ARC-07 tests: no ArcMap/ArcPy/Manager process is launched."""
import importlib.util
import pathlib
import sys
import types
import unittest
from unittest.mock import patch


SOURCE = (pathlib.Path(__file__).resolve().parents[1] /
          "arcmap_bridge" / "features" / "native_scale_bar.py")


class State:
    def __init__(self, surrounds):
        self.surrounds = surrounds
        self.typed_calls = 0
        self.refresh_calls = 0
        self.graphics_scans = 0
        self.infinite_graphics = False
        self.snap_km_division = False
        self.mxd = types.SimpleNamespace(filePath="D:/in-memory-test.mxd")
        self.items = []


class Bar:
    Units = 10
    UnitLabel = "km"
    Division = 2.5
    Divisions = 4
    Subdivisions = 2


class Element:
    def __init__(self, name, kind, bar=None):
        self.Name = name
        self.kind = kind
        self.bar = bar
        self.qi = []

    def QueryInterface(self, interface):
        self.qi.append(interface)
        if interface == "IMapSurroundFrame" and self.kind == "scale":
            return types.SimpleNamespace(
                MapSurround=types.SimpleNamespace(
                    QueryInterface=lambda expected: self.bar
                    if expected == "IScaleBar" else None))
        if interface == "IMapSurroundFrame":
            raise RuntimeError("E_NOINTERFACE")
        if interface == "IElementProperties":
            return types.SimpleNamespace(Name=self.Name)
        raise RuntimeError("Unsupported interface")


def load_with_fakes(state):
    arcpy = types.ModuleType("arcpy")
    arcpy.mapping = types.SimpleNamespace(
        ListLayoutElements=lambda mxd, kind:
            [types.SimpleNamespace(name=n) for n in state.surrounds]
            if kind == "MAPSURROUND_ELEMENT" else [],
        MapDocument=lambda key: state.mxd,
    )
    def refresh_active_view():
        state.refresh_calls += 1
        if state.snap_km_division:
            for element in state.items:
                bar = getattr(element, "bar", None)
                if bar is not None and int(getattr(bar, "Units", -1)) == 10:
                    bar.Division = 20.0

    arcpy.RefreshActiveView = refresh_active_view
    core = types.ModuleType("core")
    core.__path__ = []
    registry = types.ModuleType("core.registry")
    registry.action = lambda name: lambda fn: fn
    current_map = types.ModuleType("core.current_map")
    current_map.get_mxd = lambda: state.mxd
    safety = types.ModuleType("core.safety")
    safety.require_live_write = lambda: None
    stage3 = types.ModuleType("stage3")
    stage3.__path__ = []
    bridge = types.ModuleType("stage3.bridge")

    class Graphics:
        def __init__(self):
            self.i = 0

        def Reset(self):
            self.i = 0

        def Next(self):
            state.graphics_scans += 1
            if self.i == len(state.items):
                if state.infinite_graphics and state.items:
                    return state.items[-1]
                return None
            obj = state.items[self.i]
            self.i += 1
            return obj

    graphics = Graphics()

    class Node:
        def __init__(self, which):
            self.which = which

        def QueryInterface(self, interface):
            if self.which == "document":
                assert interface == "IMxDocument"
                return types.SimpleNamespace(PageLayout=Node("layout"))
            if self.which == "layout":
                assert interface == "IPageLayout"
                return Node("page")
            if self.which == "page":
                assert interface == "IGraphicsContainer"
                return graphics
            raise AssertionError(interface)

    def typed():
        state.typed_calls += 1
        iface = types.SimpleNamespace(
            IApplication="IApplication",
            IMxDocument="IMxDocument",
            IPageLayout="IPageLayout",
            IGraphicsContainer="IGraphicsContainer",
            IMapSurroundFrame="IMapSurroundFrame",
            IScaleBar="IScaleBar",
            IElementProperties="IElementProperties",
        )
        client = types.SimpleNamespace(
            CreateObject=lambda name, interface:
                types.SimpleNamespace(Document=Node("document")))
        return client, iface, iface, iface

    bridge._typed_arcobjects_modules = typed
    bridge._verify_current_process = lambda app: app
    modules = {
        "arcpy": arcpy,
        "core": core,
        "core.registry": registry,
        "core.current_map": current_map,
        "core.safety": safety,
        "stage3": stage3,
        "stage3.bridge": bridge,
    }
    # restore modules even if another test imported a real ArcPy package
    with patch.dict(sys.modules, modules):
        spec = importlib.util.spec_from_file_location(
            "_isolated_native_scale_bar", str(SOURCE))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    return module


class ScaleBarComGuardTests(unittest.TestCase):
    def test_empty_surrounds_never_enter_com(self):
        state = State([])
        module = load_with_fakes(state)
        output = module.list_native_scale_bars({})
        self.assertEqual([], output["scale_bars"])
        self.assertFalse(output["saved"])
        self.assertEqual(0, state.typed_calls)
        self.assertEqual(0, state.graphics_scans)
        self.assertEqual(0, state.refresh_calls)

    def test_only_candidates_receive_map_surround_query(self):
        state = State(["SCALE_BAR_A", "NORTH_ARROW"])
        state.infinite_graphics = True
        bar = Bar()
        random_graphic = Element("ZAGENT_TITLE", "text")
        target = Element("SCALE_BAR_A", "scale", bar)
        arrow = Element("NORTH_ARROW", "arrow")
        state.items = [random_graphic, target, arrow]
        module = load_with_fakes(state)
        found = module.list_native_scale_bars({})
        self.assertEqual(1, len(found["scale_bars"]))
        self.assertEqual("SCALE_BAR_A", found["scale_bars"][0]["element_name"])
        self.assertNotIn("IMapSurroundFrame", random_graphic.qi)
        self.assertIn("IMapSurroundFrame", target.qi)
        self.assertEqual(1, state.typed_calls)
        self.assertEqual(3, state.graphics_scans)

    def test_single_candidate_stops_without_none_sentinel(self):
        state = State(["SCALE_BAR_A"])
        state.infinite_graphics = True
        bar = Bar()
        target = Element("SCALE_BAR_A", "scale", bar)
        state.items = [target]
        module = load_with_fakes(state)
        found = module.list_native_scale_bars({})
        self.assertEqual(1, len(found["scale_bars"]))
        self.assertEqual("SCALE_BAR_A", found["scale_bars"][0]["element_name"])
        self.assertEqual(1, state.graphics_scans)

    def test_nonexistent_target_refuses_without_com(self):
        state = State(["SCALE_BAR_A"])
        module = load_with_fakes(state)
        with self.assertRaisesRegex(RuntimeError, "exactly one"):
            module.set_native_scale_bar({
                "element_name": "MISSING", "units": "METERS"})
        self.assertEqual(0, state.typed_calls)

    def test_existing_target_changes_units_without_save(self):
        state = State(["SCALE_BAR_A"])
        bar = Bar()
        state.items = [Element("OTHER_GRAPHIC", "text"),
                       Element("SCALE_BAR_A", "scale", bar)]
        module = load_with_fakes(state)
        result = module.set_native_scale_bar({
            "element_name": "SCALE_BAR_A",
            "units": "METERS",
            "preserve_distance": True,
        })
        self.assertEqual(9, bar.Units)
        self.assertEqual("m", bar.UnitLabel)
        self.assertEqual(2500.0, bar.Division)
        self.assertFalse(result["saved"])
        self.assertFalse(result["verified_on_arcmap"])
        self.assertTrue(result["verification_pending"])
        verified = module.list_native_scale_bars({})
        self.assertTrue(verified["ok"])
        self.assertEqual("verified", verified["change_verification"]["status"])
        self.assertEqual(2500.0, verified["change_verification"]["after"]["division"])
        self.assertEqual(1, state.refresh_calls)

    def test_post_refresh_normalization_rolls_back_exactly(self):
        state = State(["SCALE_BAR_A"])
        state.snap_km_division = True
        bar = Bar()
        bar.Units = 9
        bar.UnitLabel = "Meter"
        bar.Division = 24000.0
        state.items = [Element("SCALE_BAR_A", "scale", bar)]
        module = load_with_fakes(state)
        result = module.set_native_scale_bar({
            "element_name": "SCALE_BAR_A",
            "units": "KILOMETERS",
            "preserve_distance": True,
        })
        self.assertTrue(result["ok"])
        self.assertTrue(result["verification_pending"])
        mismatch = module.list_native_scale_bars({})
        self.assertFalse(mismatch["ok"])
        self.assertEqual("SCALE_BAR_POST_REFRESH_MISMATCH_ROLLBACK_REQUESTED",
                         mismatch["error"])
        self.assertEqual(20.0, mismatch["change_verification"]["observed"]["division"])
        restored = module.list_native_scale_bars({})
        self.assertTrue(restored["ok"])
        self.assertEqual("rolled_back", restored["change_verification"]["status"])
        self.assertEqual(9, restored["change_verification"]["after"]["units"])
        self.assertEqual("Meter", restored["change_verification"]["after"]["unit_label"])
        self.assertEqual(24000.0, restored["change_verification"]["after"]["division"])
        self.assertEqual(9, bar.Units)
        self.assertEqual("Meter", bar.UnitLabel)
        self.assertEqual(24000.0, bar.Division)
        self.assertFalse(restored["saved"])

    def test_unnamed_surround_fails_closed(self):
        state = State([""])
        module = load_with_fakes(state)
        with self.assertRaisesRegex(RuntimeError, "UNNAMED_SURROUND"):
            module.list_native_scale_bars({})
        self.assertEqual(0, state.typed_calls)

    def test_no_automatic_switch_of_page_layout(self):
        state = State([])
        module = load_with_fakes(state)
        module.list_native_scale_bars({})
        self.assertFalse(hasattr(state.mxd, "activeView"))

    def test_scan_limit_has_bounded_exit(self):
        state = State(["SCALE_BAR_A"])
        state.items = [Element("OTHER", "text")] * 5
        module = load_with_fakes(state)
        module._MAX_GRAPHICS = 3
        with self.assertRaisesRegex(RuntimeError, "GRAPHICS_LIMIT"):
            module.list_native_scale_bars({})
        self.assertLessEqual(state.graphics_scans, 3)


if __name__ == "__main__":
    unittest.main()

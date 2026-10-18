# -*- coding: utf-8 -*-
"""Native editing of existing ArcMap MapFrame IMapGrid / IMeasuredGrid objects.

Commands are dispatched on the ArcMap UI thread. A change never saves MXD.
Snapshots hold original COM objects within this bridge session, not on disk.
"""
from __future__ import print_function

import uuid
import arcpy
from core.registry import action
from core.current_map import get_mxd, get_dataframe
from core.safety import require_live_write
from stage3 import bridge as arcobjects

_GRID_SNAPSHOTS = {}
_MAX_SNAPSHOTS = 32


def _get(obj, attr, default=None):
    try:
        return getattr(obj, attr)
    except Exception:
        return default


def _frame_and_grids(name=""):
    mxd = get_mxd()
    df = get_dataframe(mxd, name)
    client, framework, arcmapui, carto = arcobjects._typed_arcobjects_modules()
    # Read-only grid inspection must not force ArcMap into PAGE_LAYOUT.
    app = client.CreateObject("esriFramework.AppRef", interface=framework.IApplication)
    arcobjects._verify_current_process(app)
    doc = app.Document.QueryInterface(arcmapui.IMxDocument)
    layout = doc.PageLayout.QueryInterface(carto.IPageLayout)
    backend = "typed ArcObjects AppRef/IMxDocument/IPageLayout"

    # The map frame must match the requested ArcPy data frame. Never edit the
    # FocusMap grid if a different dataframe was explicitly requested.
    map_obj = doc.FocusMap
    focus_name = _get(map_obj, "Name", "") or ""
    if focus_name and str(focus_name) != str(df.name):
        raise RuntimeError("CURRENT_FOCUS_MAP_MISMATCH: activate dataframe %s first" % df.name)
    graphics = layout.QueryInterface(carto.IGraphicsContainer)
    try:
        target_map = map_obj.QueryInterface(carto.IMap)
    except Exception:
        target_map = map_obj
    frame = graphics.FindFrame(target_map)
    if frame is None:
        raise RuntimeError("ArcObjects IMapFrame not found for CURRENT active map")
    return mxd, df, doc, carto, frame.QueryInterface(carto.IMapGrids), backend


def _list_grid_objects(grids):
    result = []
    for i in range(int(grids.MapGridCount)):
        accessor = _get(grids, "get_MapGrid")
        grid = accessor(i) if callable(accessor) else grids.MapGrid[i]
        result.append((i, grid))
    return result


def _locate(grids, command):
    name = command.get("grid_name")
    index = command.get("grid_index")
    if not name and index is None:
        raise ValueError("grid_name or grid_index required; never guess a grid")
    matches = []
    for i, grid in _list_grid_objects(grids):
        if name and str(_get(grid, "Name", "")) != str(name):
            continue
        if index is not None and int(index) != i:
            continue
        matches.append((i, grid))
    if len(matches) != 1:
        raise RuntimeError("Expected exactly one existing grid, found %d" % len(matches))
    return matches[0]


def _measured(grid, carto):
    iface = _get(carto, "IMeasuredGrid")
    if iface is not None and hasattr(grid, "QueryInterface"):
        return grid.QueryInterface(iface)
    if _get(grid, "XIntervalSize") is not None:
        return grid
    raise RuntimeError("Grid does not expose IMeasuredGrid X/Y intervals")


def _properties(index, grid, carto):
    data = {
        "index": index, "name": _get(grid, "Name", ""),
        "visible": _get(grid, "Visible"),
        "type": "MAP_GRID",
        "x_interval": None, "y_interval": None, "measured_grid_supported": False,
    }
    try:
        grid.QueryInterface(carto.IGraticule)
        data["type"] = "GRATICULE"
    except Exception:
        pass
    try:
        measured = _measured(grid, carto)
        data.update({
            "x_interval": float(measured.XIntervalSize),
            "y_interval": float(measured.YIntervalSize),
            "measured_grid_supported": True,
        })
    except Exception:
        pass
    line = _get(grid, "LineSymbol") or _get(grid, "GridLineSymbol")
    if line is not None:
        data["line_style"] = {
            "width": _get(line, "Width"),
            "has_color": _get(line, "Color") is not None,
        }
    label = _get(grid, "LabelFormat")
    data["label_offset"] = _get(label, "LabelOffset")
    data["border_type"] = (type(_get(grid, "Border")).__name__
                           if _get(grid, "Border") is not None else None)
    for key in ("TickLength", "SubTickLength", "SubTickCount"):
        names = {"TickLength": "tick_length", "SubTickLength": "sub_tick_length",
                 "SubTickCount": "sub_tick_count"}
        data[names[key]] = _get(grid, key)
    for name, method_name in (("label_sides", "QueryLabelVisibility"),
                              ("tick_sides", "QueryTickVisibility"),
                              ("sub_tick_sides", "QuerySubTickVisibility")):
        method = _get(grid, method_name)
        try:
            values = method()
            if len(values) == 4:
                data[name] = dict(zip(("left", "top", "right", "bottom"),
                                      [bool(v) for v in values]))
            else:
                data[name] = None
        except Exception:
            data[name] = None
    return data


def _refresh(doc):
    try:
        doc.UpdateContents()
    except Exception:
        pass
    arcpy.RefreshActiveView()
    arcpy.RefreshTOC()


def _snapshot(mxd, df, index, grid, carto):
    token = uuid.uuid4().hex
    if len(_GRID_SNAPSHOTS) >= _MAX_SNAPSHOTS:
        _GRID_SNAPSHOTS.pop(sorted(_GRID_SNAPSHOTS.keys())[0], None)
    props = _properties(index, grid, carto)
    _GRID_SNAPSHOTS[token] = {
        "file_path": str(_get(mxd, "filePath", "") or ""),
        "df_name": df.name, "index": index, "grid": grid,
        "properties": props,
        "line_symbol": _get(grid, "LineSymbol"),
        "grid_line_symbol": _get(grid, "GridLineSymbol"),
        "label_format": _get(grid, "LabelFormat"),
    }
    return token


def _apply_simple(grid, carto, values):
    if "name" in values:
        grid.Name = str(values["name"])
    if "visible" in values:
        grid.Visible = bool(values["visible"])
    if "x_interval" in values or "y_interval" in values:
        measured = _measured(grid, carto)
        if "x_interval" in values:
            x = float(values["x_interval"])
            if x <= 0:
                raise ValueError("x_interval must be > 0 in degrees/map units")
            measured.XIntervalSize = x
        if "y_interval" in values:
            y = float(values["y_interval"])
            if y <= 0:
                raise ValueError("y_interval must be > 0 in degrees/map units")
            measured.YIntervalSize = y


def _apply_line(grid, spec):
    spec = dict(spec)
    if "width" in spec and float(spec["width"]) < 0:
        raise ValueError("line width cannot be negative")
    line, _ = arcobjects._create_com(["esriDisplay.SimpleLineSymbol"])
    if "width" in spec:
        line.Width = float(spec["width"])
    if "rgb" in spec:
        rgb = spec["rgb"]
        if len(rgb) != 3:
            raise ValueError("rgb requires 3 channels")
        color, _ = arcobjects._create_com(["esriDisplay.RgbColor"])
        color.Red, color.Green, color.Blue = [max(0, min(255, int(x))) for x in rgb]
        line.Color = color
    if hasattr(grid, "LineSymbol"):
        grid.LineSymbol = line
    elif hasattr(grid, "GridLineSymbol"):
        grid.GridLineSymbol = line
    else:
        raise RuntimeError("Grid line symbol is not writable on this interface")


def _apply_sides(grid, values):
    # ArcObjects IMapGrid side order is Left, Top, Right, Bottom.
    if len(values) != 4 or any(k not in values for k in ("top", "left", "bottom", "right")):
        raise ValueError("sides need top/left/bottom/right booleans")
    method = _get(grid, "SetLabelVisibility")
    if not callable(method):
        raise RuntimeError("IMapGrid.SetLabelVisibility unavailable")
    method(bool(values["left"]), bool(values["top"]),
           bool(values["right"]), bool(values["bottom"]))


def _apply_tick_sides(grid, values, method_name):
    if len(values) != 4 or any(k not in values for k in ("top", "left", "bottom", "right")):
        raise ValueError("tick sides need top/left/bottom/right")
    method = _get(grid, method_name)
    if not callable(method):
        raise RuntimeError("%s is unavailable" % method_name)
    method(bool(values["left"]), bool(values["top"]),
           bool(values["right"]), bool(values["bottom"]))


def _restore_live(state, grid, carto):
    props = state["properties"]
    values = {}
    for name in ("name", "visible", "x_interval", "y_interval"):
        if props.get(name) is not None:
            values[name] = props[name]
    _apply_simple(grid, carto, values)
    for key, attr in (("tick_length", "TickLength"),
                      ("sub_tick_length", "SubTickLength"),
                      ("sub_tick_count", "SubTickCount")):
        if props.get(key) is not None:
            setattr(grid, attr, props[key])
    if props.get("label_offset") is not None:
        grid.LabelFormat.LabelOffset = props["label_offset"]
    if props.get("label_sides") is not None:
        _apply_sides(grid, props["label_sides"])
    for key, method in (("tick_sides", "SetTickVisibility"),
                        ("sub_tick_sides", "SetSubTickVisibility")):
        if props.get(key) is not None:
            _apply_tick_sides(grid, props[key], method)
    for prop, key in (("LineSymbol", "line_symbol"),
                      ("GridLineSymbol", "grid_line_symbol"),
                      ("LabelFormat", "label_format")):
        if state.get(key) is not None:
            try:
                setattr(grid, prop, state[key])
            except Exception:
                pass


@action("list_native_grids")
def list_native_grids(command):
    mxd, df, doc, carto, grids, backend = _frame_and_grids(command.get("data_frame") or "")
    return {"ok": True, "data_frame": df.name,
            "grids": [_properties(i, grid, carto) for i, grid in _list_grid_objects(grids)],
            "backend": backend, "saved": False}


@action("get_native_grid_properties")
def get_native_grid_properties(command):
    mxd, df, doc, carto, grids, backend = _frame_and_grids(command.get("data_frame") or "")
    index, grid = _locate(grids, command)
    return {"ok": True, "data_frame": df.name, "grid": _properties(index, grid, carto),
            "backend": backend, "saved": False}


@action("set_native_grid_properties")
def set_native_grid_properties(command):
    changes = command.get("properties") or {}
    supported = ("name", "visible", "x_interval", "y_interval", "line_style",
                 "label_sides", "tick_sides", "sub_tick_sides",
                 "tick_length", "sub_tick_length", "sub_tick_count", "label_offset")
    if not changes or any(key not in supported for key in changes):
        return {"ok": False, "error": "Supported: %s" % ", ".join(supported), "saved": False}
    blocked = require_live_write()
    if blocked:
        return blocked
    mxd, df, doc, carto, grids, backend = _frame_and_grids(command.get("data_frame") or "")
    index, grid = _locate(grids, command)
    before = _properties(index, grid, carto)
    token = _snapshot(mxd, df, index, grid, carto)
    try:
        _apply_simple(grid, carto, changes)
        if "line_style" in changes:
            _apply_line(grid, changes["line_style"])
        if "label_sides" in changes:
            _apply_sides(grid, changes["label_sides"])
        for key, method in (("tick_sides", "SetTickVisibility"),
                            ("sub_tick_sides", "SetSubTickVisibility")):
            if key in changes:
                _apply_tick_sides(grid, changes[key], method)
        for key, attr in (("tick_length", "TickLength"),
                          ("sub_tick_length", "SubTickLength"),
                          ("sub_tick_count", "SubTickCount")):
            if key in changes:
                if float(changes[key]) < 0:
                    raise ValueError("%s must be nonnegative" % key)
                setattr(grid, attr, int(changes[key]) if key == "sub_tick_count"
                        else float(changes[key]))
        if "label_offset" in changes:
            if float(changes["label_offset"]) < 0:
                raise ValueError("label_offset must be nonnegative")
            grid.LabelFormat.LabelOffset = float(changes["label_offset"])
        _refresh(doc)
        after = _properties(index, grid, carto)
        for key in ("name", "visible", "x_interval", "y_interval"):
            if key not in changes:
                continue
            actual, expected = after.get(key), changes[key]
            if key.endswith("interval"):
                if actual is None or abs(float(actual) - float(expected)) > 1e-9:
                    raise RuntimeError("%s read-back mismatch" % key)
            elif actual != expected:
                raise RuntimeError("%s read-back mismatch" % key)
        return {"ok": True, "data_frame": df.name, "before": before, "after": after,
                "grid_snapshot_token": token, "saved": False}
    except Exception as exc:
        try:
            _restore_live(_GRID_SNAPSHOTS[token], grid, carto)
            _refresh(doc)
            return {"ok": False, "error": str(exc), "rollback": "ATTEMPTED", "saved": False}
        except Exception as rollback_exc:
            return {"ok": False, "error": str(exc), "rollback_error": str(rollback_exc),
                    "manual_recovery_required": True, "saved": False}


@action("restore_native_grid_state")
def restore_native_grid_state(command):
    blocked = require_live_write()
    if blocked:
        return blocked
    token = command.get("token") or ""
    state = _GRID_SNAPSHOTS.get(token)
    if state is None:
        return {"ok": False, "error": "Unknown session grid snapshot token", "saved": False}
    mxd, df, doc, carto, grids, backend = _frame_and_grids(state["df_name"])
    if str(_get(mxd, "filePath", "") or "") != state["file_path"]:
        return {"ok": False, "error": "CURRENT_MXD_CHANGED", "saved": False}
    matches = _list_grid_objects(grids)
    if state.get("removed"):
        original_name = state["properties"]["name"]
        if any(str(_get(item, "Name", "")) == str(original_name)
               for _, item in matches):
            return {"ok": False, "error": "GRID_NAME_CONFLICT_ON_RESTORE", "saved": False}
        grids.AddMapGrid(state["grid"])
        state["removed"] = False
        matches = _list_grid_objects(grids)
        # ArcObjects AddMapGrid appends. Caller should inspect any order change.
        index, grid = matches[-1]
    else:
        if state["index"] >= len(matches):
            return {"ok": False, "error": "Original grid index no longer exists", "saved": False}
        index, grid = matches[state["index"]]
        if grid != state["grid"]:
            return {"ok": False, "error": "GRID_IDENTITY_CHANGED", "saved": False}
    _restore_live(state, grid, carto)
    _refresh(doc)
    return {"ok": True, "grid": _properties(index, grid, carto),
            "order_may_change": index != state["index"], "saved": False}


@action("create_native_grid")
def create_native_grid(command):
    blocked = require_live_write()
    if blocked:
        return blocked
    name = (command.get("grid_name") or "").strip()
    if not name:
        return {"ok": False, "error": "grid_name required", "saved": False}
    mxd, df, doc, carto, grids, backend = _frame_and_grids(command.get("data_frame") or "")
    if any(str(_get(grid, "Name", "")) == name for _, grid in _list_grid_objects(grids)):
        return {"ok": False, "error": "Grid already exists; use set_native_grid_properties", "saved": False}
    interval = float(command.get("interval", 1.0 / 120.0))
    if interval <= 0:
        return {"ok": False, "error": "interval must be > 0", "saved": False}
    created, _ = arcobjects._create_com(["esriCarto.Graticule"])
    native = created.QueryInterface(carto.IMapGrid) if hasattr(created, "QueryInterface") else created
    native.Name = name
    native.Visible = bool(command.get("visible", True))
    measured = _measured(native, carto)
    measured.XIntervalSize = interval
    measured.YIntervalSize = interval
    grids.AddMapGrid(native)
    _refresh(doc)
    found = [(i, g) for i, g in _list_grid_objects(grids)
             if str(_get(g, "Name", "")) == name]
    if len(found) != 1:
        # Remove only the new grid if a valid ArcObjects reference remains.
        try:
            grids.DeleteMapGrid(native)
        except Exception:
            pass
        return {"ok": False, "error": "Created grid not found after add", "saved": False}
    return {"ok": True, "data_frame": df.name, "grid": _properties(found[0][0], found[0][1], carto),
            "saved": False}


@action("remove_native_grid")
def remove_native_grid(command):
    blocked = require_live_write()
    if blocked:
        return blocked
    if not command.get("confirm_remove"):
        return {"ok": False, "error": "confirm_remove=true required", "saved": False}
    mxd, df, doc, carto, grids, backend = _frame_and_grids(command.get("data_frame") or "")
    index, grid = _locate(grids, command)
    token = _snapshot(mxd, df, index, grid, carto)
    grids.DeleteMapGrid(grid)
    _GRID_SNAPSHOTS[token]["removed"] = True
    _refresh(doc)
    return {"ok": True, "removed_grid": _GRID_SNAPSHOTS[token]["properties"],
            "grid_snapshot_token": token, "saved": False}

# -*- coding: utf-8 -*-
"""Native ArcMap 10.x Layer Properties. Runs only on the CURRENT ArcMap STA.

Never saves the MXD. Unsupported ArcObjects properties fail explicitly instead
of silently substituting a .lyr template or driving the Layer Properties GUI.
"""
from __future__ import print_function

import arcpy
from core.registry import action
from core.current_map import get_mxd, find_layer, safe_layer_source
from core.safety import require_live_write
from features import cartography
from stage3 import bridge as arcobjects

_MAX_UNIQUE_VALUES = 1024
_PALETTE = (
    (51, 102, 204), (230, 100, 75), (63, 155, 106),
    (193, 123, 45), (125, 96, 170), (68, 168, 180),
)


def _get(obj, name, default=None):
    try:
        return getattr(obj, name)
    except Exception:
        return default


def _single(command):
    name = (command.get("layer_name") or "").strip()
    if not name:
        raise ValueError("layer_name is required")
    matches = find_layer(get_mxd(), name, command.get("data_frame") or "")
    if len(matches) != 1:
        raise RuntimeError("Expected exactly one CURRENT layer, got %d: %s" % (len(matches), name))
    return matches[0]


def _indexed_get(obj, attr, key):
    method = _get(obj, "get_" + attr)
    if callable(method):
        return method(key)
    prop = getattr(obj, attr)
    return prop[key]


def _indexed_set(obj, attr, key, value):
    method = _get(obj, "set_" + attr)
    if callable(method):
        return method(key, value)
    prop = getattr(obj, attr)
    prop[key] = value


def _geo(lyr):
    client, framework, arcmapui, carto = arcobjects._typed_arcobjects_modules()
    obj = _get(lyr, "_arc_object")
    if obj is not None and hasattr(obj, "QueryInterface"):
        try:
            return obj.QueryInterface(carto.IGeoFeatureLayer), carto
        except Exception:
            pass

    # ArcPy does not guarantee a typed QueryInterface on _arc_object.
    # Fall back to the exact CURRENT focus map, never GetActiveObject from an
    # arbitrary ArcMap process and never a loosely matched layer name.
    mxd = get_mxd()
    frames = find_layer(mxd, lyr.name)
    if len(frames) != 1:
        raise RuntimeError("ArcObjects lookup requires a globally unambiguous layer name")
    df_name = frames[0][0].name
    if mxd.activeDataFrame.name != df_name:
        raise RuntimeError("Activate data frame '%s' before native ArcObjects renderer editing" % df_name)
    app = client.CreateObject("esriFramework.AppRef", interface=framework.IApplication)
    arcobjects._verify_current_process(app)
    doc = app.Document.QueryInterface(arcmapui.IMxDocument)
    map_obj = doc.FocusMap.QueryInterface(carto.IMap)
    if str(_get(map_obj, "Name", "")) != str(df_name):
        raise RuntimeError("CURRENT_FOCUS_MAP_MISMATCH")
    found = []
    for index in range(int(map_obj.LayerCount)):
        method = _get(map_obj, "get_Layer")
        item = method(index) if callable(method) else map_obj.Layer[index]
        if str(_get(item, "Name", "")) == str(lyr.name):
            found.append(item)
    if len(found) != 1:
        raise RuntimeError("Native ArcObjects layer resolution is ambiguous/unavailable")
    return found[0].QueryInterface(carto.IGeoFeatureLayer), carto


def _unique(lyr):
    geo, carto = _geo(lyr)
    return geo, geo.Renderer.QueryInterface(carto.IUniqueValueRenderer)


def _categories(renderer):
    rows = []
    for i in range(int(renderer.ValueCount)):
        value = str(_indexed_get(renderer, "Value", i))
        rows.append({
            "value": value,
            "label": str(_indexed_get(renderer, "Label", value)),
        })
    return rows


def _renderer_state(lyr):
    state = {
        "symbology_type": _get(lyr, "symbologyType") or "OTHER",
        "renderer_backend": "ArcObjects",
        "value_field": None,
        "show_other_values": None,
        "categories": [],
    }
    try:
        _, uv = _unique(lyr)
        if int(uv.FieldCount) == 1:
            state["value_field"] = _indexed_get(uv, "Field", 0)
        state["show_other_values"] = bool(uv.UseDefaultSymbol)
        state["categories"] = _categories(uv)
        state["renderer_type"] = "UNIQUE_VALUES"
    except Exception as exc:
        state["renderer_type"] = state["symbology_type"]
        state["detail"] = str(exc)
    return state


def _refresh():
    arcpy.RefreshTOC()
    arcpy.RefreshActiveView()


def _symbol(shape, style):
    style = dict(style or {})
    rgb = style.get("fill_rgb", [90, 140, 205])
    outline = style.get("outline_rgb", [42, 49, 60])
    width = float(style.get("outline_width", 0.8))
    if len(rgb) != 3 or len(outline) != 3 or width < 0:
        raise ValueError("fill_rgb/outline_rgb require 3 channels; outline_width must be >= 0")
    color, _ = arcobjects._create_com(["esriDisplay.RgbColor"])
    color.Red, color.Green, color.Blue = [max(0, min(255, int(x))) for x in rgb]
    color.Transparency = int(round(255 * (1.0 - max(0.0, min(100.0, float(style.get("transparency", 0)))) / 100.0)))
    border, _ = arcobjects._create_com(["esriDisplay.RgbColor"])
    border.Red, border.Green, border.Blue = [max(0, min(255, int(x))) for x in outline]
    shape = (shape or "").lower()
    if shape in ("polygon", "multipatch"):
        fill, _ = arcobjects._create_com(["esriDisplay.SimpleFillSymbol"])
        line, _ = arcobjects._create_com(["esriDisplay.SimpleLineSymbol"])
        line.Color, line.Width = border, width
        fill.Color, fill.Outline = color, line
        return fill
    if shape in ("polyline", "line"):
        line, _ = arcobjects._create_com(["esriDisplay.SimpleLineSymbol"])
        line.Color, line.Width = color, width
        return line
    if shape in ("point", "multipoint"):
        marker, _ = arcobjects._create_com(["esriDisplay.SimpleMarkerSymbol"])
        marker.Color = color
        marker.Size = float(style.get("marker_size", 5.0))
        return marker
    raise RuntimeError("Unique values renderer only supports feature layers; geometry=%s" % shape)


def _style_for(command, value, index):
    styles = command.get("category_styles") or {}
    specific = styles.get(value) or {}
    result = dict(specific)
    result.setdefault("fill_rgb", list(_PALETTE[index % len(_PALETTE)]))
    return result


def _scan_values(lyr, field, limit=_MAX_UNIQUE_VALUES):
    names = [f.name for f in arcpy.ListFields(lyr)]
    if field not in names:
        raise ValueError("Field not found: %s" % field)
    # The dataset is scanned, not edited. Refuse high-cardinality renderers.
    values = set()
    with arcpy.da.SearchCursor(lyr, [field]) as cursor:
        for row in cursor:
            value = "<Null>" if row[0] is None else str(row[0])
            values.add(value)
            if len(values) > int(limit):
                raise ValueError("Unique value limit exceeded (%d); choose another field" % int(limit))
    return sorted(values)


def _snapshot(command):
    result = cartography.capture_layer_style(command)
    if not result.get("ok"):
        raise RuntimeError("Style snapshot failed: %s" % result)
    return result["token"]


def _restore(command, token):
    return cartography.restore_layer_style({
        "token": token,
        "layer_name": command["layer_name"],
        "data_frame": command.get("data_frame", ""),
    })


def _with_rollback(command, operation):
    blocked = require_live_write()
    if blocked:
        return blocked
    token = _snapshot(command)
    try:
        result = operation()
        if not result.get("ok", True):
            raise RuntimeError(result.get("error") or "Postcondition failed")
        result.update({"ok": True, "rollback_style_token": token, "saved": False})
        return result
    except Exception as exc:
        try:
            restored = _restore(command, token)
            return {"ok": False, "error": str(exc), "rollback": restored, "saved": False}
        except Exception as restore_exc:
            return {"ok": False, "error": str(exc), "rollback_error": str(restore_exc),
                    "manual_recovery_required": True, "saved": False}


@action("get_native_layer_properties")
def get_native_layer_properties(command):
    df, lyr = _single(command)
    fields = []
    try:
        fields = [{"name": f.name, "alias": f.aliasName, "type": f.type}
                  for f in arcpy.ListFields(lyr)]
    except Exception:
        pass
    return {
        "ok": True, "layer_name": lyr.name, "data_frame": df.name, "saved": False,
        "general": {"name": lyr.name, "visible": _get(lyr, "visible"),
                    "is_feature_layer": _get(lyr, "isFeatureLayer", False)},
        "source": {"path": safe_layer_source(lyr), "broken": _get(lyr, "isBroken")},
        "definition_query": _get(lyr, "definitionQuery"),
        "display": {"transparency": _get(lyr, "transparency"),
                    "min_scale": _get(lyr, "minScale"), "max_scale": _get(lyr, "maxScale")},
        "labels": {"enabled": _get(lyr, "showLabels"),
                   "classes": [{"index": i, "expression": _get(c, "expression"),
                                "sql_query": _get(c, "SQLQuery")} for i, c in
                               enumerate(_get(lyr, "labelClasses", []) or [])]},
        "fields": fields,
        "symbology": _renderer_state(lyr),
        "capability_map": {
            "general": "arcpy_read_write", "source": "read_only_use_replace_data_source",
            "definition_query": "arcpy_read_write", "display": "arcpy_read_write",
            "labels": "arcpy_read_write", "fields": "read_only",
            "symbology": "arcobjects_native", "joins_relates": "unsupported",
            "time_html_popup_advanced": "not_implemented",
        },
    }


@action("get_native_renderer_state")
def get_native_renderer_state(command):
    df, lyr = _single(command)
    state = _renderer_state(lyr)
    state.update({"ok": True, "layer_name": lyr.name, "data_frame": df.name, "saved": False})
    return state


@action("set_native_layer_properties")
def set_native_layer_properties(command):
    props = command.get("properties") or {}
    permitted = ("name", "visible", "definition_query", "transparency",
                 "min_scale", "max_scale", "show_labels")
    if not props or any(key not in permitted for key in props):
        return {"ok": False, "error": "Supported properties: %s" % ", ".join(permitted), "saved": False}
    blocked = require_live_write()
    if blocked:
        return blocked
    df, lyr = _single(command)
    mapping = {"name": "name", "visible": "visible", "definition_query": "definitionQuery",
               "transparency": "transparency", "min_scale": "minScale",
               "max_scale": "maxScale", "show_labels": "showLabels"}
    before = {}
    for key in props:
        before[key] = getattr(lyr, mapping[key])
    try:
        if "transparency" in props and not 0 <= float(props["transparency"]) <= 100:
            raise ValueError("transparency must be 0..100")
        for key, value in props.items():
            setattr(lyr, mapping[key], value)
        for key, value in props.items():
            if getattr(lyr, mapping[key]) != value:
                raise RuntimeError("Property read-back mismatch: %s" % key)
        _refresh()
        return {"ok": True, "data_frame": df.name, "layer_name": lyr.name,
                "before": before, "after": props, "saved": False}
    except Exception as exc:
        restored = []
        for key, value in before.items():
            try:
                setattr(lyr, mapping[key], value)
                restored.append(key)
            except Exception:
                pass
        _refresh()
        return {"ok": False, "error": str(exc), "restored": restored,
                "manual_recovery_required": len(restored) != len(before), "saved": False}


def _install_unique(command):
    df, lyr = _single(command)
    field = (command.get("field_name") or "").strip()
    if not field:
        raise ValueError("field_name is required")
    values = _scan_values(lyr, field) if command.get("refresh_values", True) else list(command.get("values") or [])
    if not values:
        raise ValueError("No categories discovered/provided")
    geo, carto = _geo(lyr)
    previous_labels = {}
    previous_symbols = {}
    try:
        _, old = _unique(lyr)
        for row in _categories(old):
            previous_labels[row["value"]] = row["label"]
            previous_symbols[row["value"]] = _indexed_get(old, "Symbol", row["value"])
    except Exception:
        pass
    renderer, _ = arcobjects._create_com(["esriCarto.UniqueValueRenderer"])
    renderer = renderer.QueryInterface(carto.IUniqueValueRenderer) if hasattr(renderer, "QueryInterface") else renderer
    renderer.FieldCount = 1
    _indexed_set(renderer, "Field", 0, field)
    renderer.UseDefaultSymbol = bool(command.get("show_other_values", False))
    shape = _get(arcpy.Describe(lyr), "shapeType", "")
    for i, value in enumerate(values):
        value = str(value)
        symbol = previous_symbols.get(value) if command.get("preserve_existing_styles", True) else None
        if symbol is None or value in (command.get("category_styles") or {}):
            symbol = _symbol(shape, _style_for(command, value, i))
        renderer.AddValue(value, "", symbol)
        label = (command.get("category_labels") or {}).get(value, previous_labels.get(value, value))
        _indexed_set(renderer, "Label", value, label)
    geo.Renderer = renderer
    _refresh()
    state = _renderer_state(lyr)
    if state["renderer_type"] != "UNIQUE_VALUES" or str(state["value_field"]) != field:
        raise RuntimeError("Native renderer read-back did not confirm UNIQUE_VALUES / field")
    if set(x["value"] for x in state["categories"]) != set(str(x) for x in values):
        raise RuntimeError("Category read-back mismatch")
    if state["show_other_values"] != bool(command.get("show_other_values", False)):
        raise RuntimeError("UseDefaultSymbol read-back mismatch")
    return {"ok": True, "data_frame": df.name, "layer_name": lyr.name,
            "renderer": state, "category_count": len(values)}


@action("set_native_unique_values_renderer")
def set_native_unique_values_renderer(command):
    return _with_rollback(command, lambda: _install_unique(command))


@action("refresh_native_unique_values")
def refresh_native_unique_values(command):
    df, lyr = _single(command)
    state = _renderer_state(lyr)
    field = command.get("field_name") or state.get("value_field")
    if not field:
        return {"ok": False, "error": "Not a single-field native UNIQUE_VALUES renderer", "saved": False}
    updated = dict(command)
    updated["field_name"] = field
    updated["refresh_values"] = True
    updated.setdefault("show_other_values", state["show_other_values"])
    return set_native_unique_values_renderer(updated)


@action("update_native_category")
def update_native_category(command):
    value = str(command.get("value") or "")
    if not value:
        return {"ok": False, "error": "value is required", "saved": False}
    def change():
        df, lyr = _single(command)
        geo, renderer = _unique(lyr)
        categories = _categories(renderer)
        if value not in [x["value"] for x in categories]:
            raise ValueError("Category not present: %s" % value)
        if command.get("remove", False):
            renderer.RemoveValue(value)
        else:
            if command.get("label") is not None:
                _indexed_set(renderer, "Label", value, command["label"])
            if command.get("symbol") is not None:
                shape = _get(arcpy.Describe(lyr), "shapeType", "")
                _indexed_set(renderer, "Symbol", value, _symbol(shape, command["symbol"]))
        if command.get("show_other_values") is not None:
            renderer.UseDefaultSymbol = bool(command["show_other_values"])
        geo.Renderer = renderer
        _refresh()
        state = _renderer_state(lyr)
        if command.get("remove") and value in [x["value"] for x in state["categories"]]:
            raise RuntimeError("Category still present after removal")
        return {"ok": True, "renderer": state, "layer_name": lyr.name, "data_frame": df.name}
    return _with_rollback(command, change)

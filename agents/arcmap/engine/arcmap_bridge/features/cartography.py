# -*- coding: utf-8 -*-
from __future__ import print_function

import os
import uuid
import arcpy

from core.registry import action
from core.current_map import get_mxd, find_layer, safe_layer_source
from core.safety import require_live_write
from core.config import DATA_ROOT

_STYLE_SNAPSHOTS = {}
_STYLE_DIR = os.path.join(DATA_ROOT, "runtime", "styles")


def _safe_get(obj, name, default=None):
    try:
        return getattr(obj, name)
    except Exception:
        return default


def _ensure_style_dir():
    if not os.path.isdir(_STYLE_DIR):
        os.makedirs(_STYLE_DIR)


def _single_layer(mxd, layer_name, data_frame=""):
    matches = find_layer(mxd, layer_name, data_frame)
    if not matches:
        raise RuntimeError("Layer not found: {0}".format(layer_name))
    if len(matches) != 1:
        raise RuntimeError(
            "Layer name is ambiguous ({0} matches): {1}".format(
                len(matches), layer_name))
    return matches[0]


def _find_by_snapshot(mxd, state, override_name="", override_df=""):
    if override_name:
        return _single_layer(mxd, override_name, override_df)

    df_name = state.get("data_frame", "")
    layer_name = state.get("layer_name", "")
    matches = find_layer(mxd, layer_name, df_name)
    if len(matches) == 1:
        return matches[0]

    source = state.get("data_source", "") or ""
    source_matches = []
    for df in arcpy.mapping.ListDataFrames(mxd):
        if df_name and df.name != df_name:
            continue
        for lyr in arcpy.mapping.ListLayers(mxd, "", df):
            try:
                if source and safe_layer_source(lyr) == source:
                    source_matches.append((df, lyr))
            except Exception:
                pass
    if len(source_matches) == 1:
        return source_matches[0]

    raise RuntimeError("Style target could not be resolved safely.")


def _field_names(lyr):
    try:
        return [field.name for field in arcpy.ListFields(lyr)]
    except Exception:
        source = safe_layer_source(lyr)
        if source:
            return [field.name for field in arcpy.ListFields(source)]
    return []


@action("capture_layer_style")
def capture_layer_style(command):
    blocked = require_live_write()
    if blocked:
        return blocked

    mxd = get_mxd()
    df, lyr = _single_layer(
        mxd,
        command.get("layer_name", ""),
        command.get("data_frame", "")
    )

    _ensure_style_dir()
    token = str(uuid.uuid4())
    path = os.path.join(_STYLE_DIR, "{0}.lyr".format(token))

    arcpy.SaveToLayerFile_management(lyr, path, "ABSOLUTE")
    _STYLE_SNAPSHOTS[token] = {
        "path": path,
        "data_frame": df.name,
        "layer_name": lyr.name,
        "data_source": safe_layer_source(lyr)
    }

    return {
        "ok": True,
        "token": token,
        "layer_name": lyr.name,
        "data_frame": df.name,
        "path": path,
        "saved": False
    }


@action("list_style_snapshots")
def list_style_snapshots(command):
    rows = []
    for token in sorted(_STYLE_SNAPSHOTS.keys()):
        state = _STYLE_SNAPSHOTS[token]
        rows.append({
            "token": token,
            "layer_name": state.get("layer_name", ""),
            "data_frame": state.get("data_frame", ""),
            "data_source": state.get("data_source", ""),
            "path": state.get("path", ""),
            "present": os.path.isfile(state.get("path", ""))
        })
    return {"ok": True, "count": len(rows), "snapshots": rows, "saved": False}


@action("restore_layer_style")
def restore_layer_style(command):
    blocked = require_live_write()
    if blocked:
        return blocked

    token = command.get("token", "")
    state = _STYLE_SNAPSHOTS.get(token)
    if state is None:
        return {
            "ok": False,
            "error": "Unknown style snapshot token: {0}".format(token),
            "saved": False
        }

    path = state.get("path", "")
    if not os.path.isfile(path):
        return {
            "ok": False,
            "error": "Style snapshot file is missing: {0}".format(path),
            "saved": False
        }

    mxd = get_mxd()
    df, target = _find_by_snapshot(
        mxd,
        state,
        command.get("layer_name", ""),
        command.get("data_frame", "")
    )
    source_layer = arcpy.mapping.Layer(path)
    arcpy.mapping.UpdateLayer(df, target, source_layer, True)
    arcpy.RefreshTOC()
    arcpy.RefreshActiveView()

    return {
        "ok": True,
        "token": token,
        "layer_name": target.name,
        "data_frame": df.name,
        "saved": False
    }


@action("delete_style_snapshot")
def delete_style_snapshot(command):
    blocked = require_live_write()
    if blocked:
        return blocked

    token = command.get("token", "")
    state = _STYLE_SNAPSHOTS.get(token)
    if state is None:
        return {
            "ok": False,
            "error": "Unknown style snapshot token: {0}".format(token),
            "saved": False
        }

    path = state.get("path", "")
    if path and os.path.isfile(path):
        os.remove(path)
    try:
        del _STYLE_SNAPSHOTS[token]
    except Exception:
        pass

    return {"ok": True, "token": token, "deleted": True, "saved": False}


@action("get_renderer_capabilities")
def get_renderer_capabilities(command):
    mxd = get_mxd()
    df, lyr = _single_layer(
        mxd,
        command.get("layer_name", ""),
        command.get("data_frame", "")
    )
    sym = _safe_get(lyr, "symbology", None)
    props = {}
    for prop in (
            "valueField", "normalization", "numClasses", "classificationMethod",
            "classBreakValues", "classBreakLabels", "classValues", "classLabels",
            "showOtherValues"):
        props[prop] = bool(sym is not None and hasattr(sym, prop))

    return {
        "ok": True,
        "data_frame": df.name,
        "layer_name": lyr.name,
        "symbology_type": _safe_get(lyr, "symbologyType", None),
        "writable_properties": props,
        "saved": False
    }


@action("set_label_class")
def set_label_class(command):
    blocked = require_live_write()
    if blocked:
        return blocked

    mxd = get_mxd()
    df, lyr = _single_layer(
        mxd,
        command.get("layer_name", ""),
        command.get("data_frame", "")
    )
    try:
        classes = lyr.labelClasses
    except Exception:
        return {
            "ok": False,
            "error": "Layer does not expose label classes: {0}".format(lyr.name),
            "saved": False
        }

    index = int(command.get("class_index", 0))
    if index < 0 or index >= len(classes):
        return {
            "ok": False,
            "error": "class_index out of range: {0}".format(index),
            "class_count": len(classes),
            "saved": False
        }

    lc = classes[index]
    before = {
        "expression": _safe_get(lc, "expression", "") or "",
        "sql_query": _safe_get(lc, "SQLQuery", "") or "",
        "show_class_labels": _safe_get(lc, "showClassLabels", None),
        "expression_parser": _safe_get(lc, "expressionParser", None)
    }

    if command.get("expression") is not None:
        lc.expression = command.get("expression") or ""
    if command.get("sql_query") is not None:
        lc.SQLQuery = command.get("sql_query") or ""
    if command.get("show_class_labels") is not None:
        lc.showClassLabels = bool(command.get("show_class_labels"))
    if command.get("expression_parser") is not None:
        try:
            lc.expressionParser = command.get("expression_parser")
        except Exception:
            pass
    if command.get("show_labels") is not None:
        lyr.showLabels = bool(command.get("show_labels"))

    arcpy.RefreshActiveView()
    after = {
        "expression": _safe_get(lc, "expression", "") or "",
        "sql_query": _safe_get(lc, "SQLQuery", "") or "",
        "show_class_labels": _safe_get(lc, "showClassLabels", None),
        "expression_parser": _safe_get(lc, "expressionParser", None),
        "show_labels": _safe_get(lyr, "showLabels", None)
    }
    return {
        "ok": True,
        "data_frame": df.name,
        "layer_name": lyr.name,
        "class_index": index,
        "before": before,
        "after": after,
        "saved": False
    }


@action("set_unique_value_field")
def set_unique_value_field(command):
    blocked = require_live_write()
    if blocked:
        return blocked

    mxd = get_mxd()
    df, lyr = _single_layer(
        mxd,
        command.get("layer_name", ""),
        command.get("data_frame", "")
    )
    field_name = command.get("field_name", "")
    if field_name not in _field_names(lyr):
        return {
            "ok": False,
            "error": "Field not found: {0}".format(field_name),
            "saved": False
        }

    sym_type = _safe_get(lyr, "symbologyType", "") or ""
    sym = _safe_get(lyr, "symbology", None)
    if sym is None or not hasattr(sym, "valueField"):
        return {
            "ok": False,
            "error": "Current renderer does not expose valueField. Apply a UNIQUE_VALUES .lyr template first.",
            "symbology_type": sym_type,
            "saved": False
        }

    old_field = _safe_get(sym, "valueField", None)
    sym.valueField = field_name
    if bool(command.get("refresh_values", True)) and hasattr(sym, "addAllValues"):
        try:
            sym.addAllValues()
        except Exception:
            pass
    lyr.symbology = sym
    arcpy.RefreshTOC()
    arcpy.RefreshActiveView()

    return {
        "ok": True,
        "data_frame": df.name,
        "layer_name": lyr.name,
        "symbology_type": sym_type,
        "old_field": old_field,
        "value_field": _safe_get(lyr.symbology, "valueField", field_name),
        "saved": False
    }


@action("set_class_breaks")
def set_class_breaks(command):
    blocked = require_live_write()
    if blocked:
        return blocked

    mxd = get_mxd()
    df, lyr = _single_layer(
        mxd,
        command.get("layer_name", ""),
        command.get("data_frame", "")
    )
    field_name = command.get("field_name", "")
    breaks = command.get("break_values", []) or []
    try:
        breaks = [float(value) for value in breaks]
    except Exception:
        return {"ok": False, "error": "break_values must be numeric", "saved": False}
    if len(breaks) < 2:
        return {"ok": False, "error": "At least two break values are required", "saved": False}
    if breaks != sorted(breaks):
        return {"ok": False, "error": "break_values must be sorted ascending", "saved": False}
    if field_name not in _field_names(lyr):
        return {"ok": False, "error": "Field not found: {0}".format(field_name), "saved": False}

    sym_type = _safe_get(lyr, "symbologyType", "") or ""
    sym = _safe_get(lyr, "symbology", None)
    if sym is None or not hasattr(sym, "classBreakValues") or not hasattr(sym, "valueField"):
        return {
            "ok": False,
            "error": "Current renderer does not expose classBreakValues. Apply a graduated .lyr template first.",
            "symbology_type": sym_type,
            "saved": False
        }

    old_field = _safe_get(sym, "valueField", None)
    old_breaks = list(_safe_get(sym, "classBreakValues", []) or [])
    sym.valueField = field_name
    if hasattr(sym, "numClasses"):
        try:
            sym.numClasses = len(breaks) - 1
        except Exception:
            pass
    if hasattr(sym, "classificationMethod"):
        try:
            sym.classificationMethod = "Manual"
        except Exception:
            pass
    sym.classBreakValues = breaks
    lyr.symbology = sym
    arcpy.RefreshTOC()
    arcpy.RefreshActiveView()

    return {
        "ok": True,
        "data_frame": df.name,
        "layer_name": lyr.name,
        "symbology_type": sym_type,
        "old_field": old_field,
        "old_break_values": old_breaks,
        "value_field": _safe_get(lyr.symbology, "valueField", field_name),
        "break_values": list(_safe_get(lyr.symbology, "classBreakValues", breaks) or []),
        "saved": False
    }

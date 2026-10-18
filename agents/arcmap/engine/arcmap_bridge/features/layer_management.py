# -*- coding: utf-8 -*-
from __future__ import print_function

import os
import uuid
import arcpy

from core.registry import action
from core.current_map import get_mxd, get_dataframe, find_layer, safe_layer_source
from core.safety import require_live_write


# Session-scoped temporary layers created only by this feature module.
# Generic destructive layer removal remains blocked by Safe Mode.
_TEMP_LAYERS = {}


def _safe_get(obj, name, default=None):
    try:
        return getattr(obj, name)
    except Exception:
        return default


def _supports(layer, capability):
    try:
        return bool(layer.supports(capability))
    except Exception:
        return False


def _single_layer(mxd, layer_name, data_frame=""):
    if not layer_name:
        raise RuntimeError("layer_name is required")
    matches = find_layer(mxd, layer_name, data_frame)
    if not matches:
        raise RuntimeError("Layer not found: {0}".format(layer_name))
    if len(matches) != 1:
        raise RuntimeError(
            "Layer name is ambiguous ({0} matches): {1}".format(
                len(matches), layer_name))
    return matches[0]


def _layer_order(mxd, df):
    rows = []
    for index, lyr in enumerate(arcpy.mapping.ListLayers(mxd, "", df)):
        rows.append({
            "index": index,
            "name": lyr.name,
            "long_name": _safe_get(lyr, "longName", lyr.name),
            "data_source": safe_layer_source(lyr),
            "visible": _safe_get(lyr, "visible", None),
            "is_group_layer": bool(_safe_get(lyr, "isGroupLayer", False))
        })
    return rows


def _path_exists(path):
    if not path:
        return False
    try:
        if arcpy.Exists(path):
            return True
    except Exception:
        pass
    try:
        return os.path.exists(path)
    except Exception:
        return False


@action("get_layer_extent")
def get_layer_extent(command):
    mxd = get_mxd()
    df, lyr = _single_layer(
        mxd,
        command.get("layer_name", ""),
        command.get("data_frame", "")
    )

    extent = None
    try:
        extent = lyr.getExtent()
    except Exception:
        source = safe_layer_source(lyr)
        if source:
            try:
                extent = arcpy.Describe(source).extent
            except Exception:
                extent = None

    if extent is None:
        return {
            "ok": False,
            "error": "Extent is not available for layer: {0}".format(lyr.name),
            "data_frame": df.name,
            "layer_name": lyr.name,
            "saved": False
        }

    return {
        "ok": True,
        "data_frame": df.name,
        "layer_name": lyr.name,
        "extent": {
            "xmin": float(extent.XMin),
            "ymin": float(extent.YMin),
            "xmax": float(extent.XMax),
            "ymax": float(extent.YMax)
        },
        "center": {
            "x": float((extent.XMin + extent.XMax) / 2.0),
            "y": float((extent.YMin + extent.YMax) / 2.0)
        },
        "saved": False
    }


@action("get_layer_capabilities")
def get_layer_capabilities(command):
    mxd = get_mxd()
    df, lyr = _single_layer(
        mxd,
        command.get("layer_name", ""),
        command.get("data_frame", "")
    )

    capability_names = [
        "DATASOURCE",
        "DEFINITIONQUERY",
        "LABELCLASSES",
        "SELECTION",
        "SHOWLABELS",
        "SYMBOLOGY",
        "SYMBOLOGYTYPE",
        "TRANSPARENCY",
        "VISIBLE",
        "WORKSPACEPATH"
    ]

    capabilities = {}
    for capability in capability_names:
        capabilities[capability] = _supports(lyr, capability)

    return {
        "ok": True,
        "data_frame": df.name,
        "layer_name": lyr.name,
        "is_feature_layer": bool(_safe_get(lyr, "isFeatureLayer", False)),
        "is_raster_layer": bool(_safe_get(lyr, "isRasterLayer", False)),
        "is_group_layer": bool(_safe_get(lyr, "isGroupLayer", False)),
        "capabilities": capabilities,
        "saved": False
    }


@action("get_broken_data_sources")
def get_broken_data_sources(command):
    mxd = get_mxd()
    broken = []
    try:
        objects = arcpy.mapping.ListBrokenDataSources(mxd)
    except Exception as exc:
        return {
            "ok": False,
            "error": str(exc),
            "broken": [],
            "count": 0,
            "saved": False
        }

    # Build a best-effort frame lookup by layer name.
    frame_by_name = {}
    for df in arcpy.mapping.ListDataFrames(mxd):
        for lyr in arcpy.mapping.ListLayers(mxd, "", df):
            frame_by_name.setdefault(lyr.name, []).append(df.name)

    for obj in objects:
        name = _safe_get(obj, "name", "")
        frames = frame_by_name.get(name, [])
        broken.append({
            "name": name,
            "long_name": _safe_get(obj, "longName", name),
            "data_source": safe_layer_source(obj),
            "data_frames": frames,
            "is_layer": hasattr(obj, "isGroupLayer")
        })

    return {
        "ok": True,
        "count": len(broken),
        "broken": broken,
        "saved": False
    }


@action("validate_data_source")
def validate_data_source(command):
    mxd = get_mxd()
    layer_name = command.get("layer_name", "")
    data_frame = command.get("data_frame", "")
    path = command.get("path", "")

    resolved_from = "path"
    if layer_name:
        df, lyr = _single_layer(mxd, layer_name, data_frame)
        path = safe_layer_source(lyr)
        resolved_from = "layer"
        df_name = df.name
    else:
        df_name = data_frame

    if not path:
        return {
            "ok": False,
            "error": "Provide layer_name or path.",
            "exists": False,
            "saved": False
        }

    exists = _path_exists(path)
    result = {
        "ok": True,
        "exists": bool(exists),
        "path": path,
        "resolved_from": resolved_from,
        "data_frame": df_name,
        "layer_name": layer_name,
        "describe": {},
        "saved": False
    }

    if exists:
        try:
            desc = arcpy.Describe(path)
            result["describe"] = {
                "data_type": _safe_get(desc, "dataType", None),
                "shape_type": _safe_get(desc, "shapeType", None),
                "catalog_path": _safe_get(desc, "catalogPath", path),
                "spatial_reference": _safe_get(
                    _safe_get(desc, "spatialReference", None),
                    "name",
                    None
                )
            }
        except Exception:
            pass

    return result


@action("rename_layer")
def rename_layer(command):
    blocked = require_live_write()
    if blocked:
        return blocked

    new_name = (command.get("new_name", "") or "").strip()
    if not new_name:
        return {"ok": False, "error": "new_name is required", "saved": False}

    mxd = get_mxd()
    df, lyr = _single_layer(
        mxd,
        command.get("layer_name", ""),
        command.get("data_frame", "")
    )

    # Prevent introducing avoidable ambiguity in the same frame.
    for other in arcpy.mapping.ListLayers(mxd, "", df):
        if other is not lyr and other.name == new_name:
            return {
                "ok": False,
                "error": "A layer named '{0}' already exists in data frame '{1}'.".format(
                    new_name, df.name),
                "saved": False
            }

    old_name = lyr.name
    try:
        lyr.name = new_name
    except Exception as exc:
        return {
            "ok": False,
            "error": "ArcMap did not allow layer rename: {0}".format(exc),
            "old_name": old_name,
            "saved": False
        }

    arcpy.RefreshTOC()
    arcpy.RefreshActiveView()

    return {
        "ok": True,
        "data_frame": df.name,
        "old_name": old_name,
        "new_name": lyr.name,
        "saved": False
    }


@action("move_layer")
def move_layer(command):
    blocked = require_live_write()
    if blocked:
        return blocked

    position = (command.get("position", "BEFORE") or "BEFORE").upper()
    if position not in ("BEFORE", "AFTER"):
        return {
            "ok": False,
            "error": "position must be BEFORE or AFTER",
            "saved": False
        }

    mxd = get_mxd()
    data_frame = command.get("data_frame", "")
    df, move_lyr = _single_layer(
        mxd, command.get("layer_name", ""), data_frame)
    ref_df, ref_lyr = _single_layer(
        mxd, command.get("reference_layer", ""), df.name)

    if ref_df.name != df.name:
        return {
            "ok": False,
            "error": "Both layers must be in the same data frame.",
            "saved": False
        }

    if move_lyr.name == ref_lyr.name:
        return {
            "ok": False,
            "error": "layer_name and reference_layer must be different.",
            "saved": False
        }

    arcpy.mapping.MoveLayer(df, ref_lyr, move_lyr, position)
    arcpy.RefreshTOC()
    arcpy.RefreshActiveView()

    return {
        "ok": True,
        "data_frame": df.name,
        "layer_name": move_lyr.name,
        "reference_layer": ref_lyr.name,
        "position": position,
        "layer_order": _layer_order(mxd, df),
        "saved": False
    }


@action("set_layer_transparency")
def set_layer_transparency(command):
    blocked = require_live_write()
    if blocked:
        return blocked

    try:
        transparency = int(command.get("transparency", 0))
    except Exception:
        return {"ok": False, "error": "transparency must be an integer", "saved": False}

    if transparency < 0 or transparency > 100:
        return {
            "ok": False,
            "error": "transparency must be between 0 and 100",
            "saved": False
        }

    mxd = get_mxd()
    df, lyr = _single_layer(
        mxd,
        command.get("layer_name", ""),
        command.get("data_frame", "")
    )

    old_value = _safe_get(lyr, "transparency", None)
    try:
        lyr.transparency = transparency
    except Exception as exc:
        return {
            "ok": False,
            "error": "Layer transparency is not writable: {0}".format(exc),
            "saved": False
        }

    arcpy.RefreshActiveView()
    return {
        "ok": True,
        "data_frame": df.name,
        "layer_name": lyr.name,
        "old_transparency": old_value,
        "transparency": _safe_get(lyr, "transparency", transparency),
        "saved": False
    }


@action("set_layer_scale_range")
def set_layer_scale_range(command):
    blocked = require_live_write()
    if blocked:
        return blocked

    try:
        min_scale = float(command.get("min_scale", 0.0))
        max_scale = float(command.get("max_scale", 0.0))
    except Exception:
        return {
            "ok": False,
            "error": "min_scale and max_scale must be numeric",
            "saved": False
        }

    if min_scale < 0 or max_scale < 0:
        return {
            "ok": False,
            "error": "Scale values must be >= 0. Use 0 for no limit.",
            "saved": False
        }

    mxd = get_mxd()
    df, lyr = _single_layer(
        mxd,
        command.get("layer_name", ""),
        command.get("data_frame", "")
    )

    old_min = _safe_get(lyr, "minScale", None)
    old_max = _safe_get(lyr, "maxScale", None)

    try:
        lyr.minScale = min_scale
        lyr.maxScale = max_scale
    except Exception as exc:
        return {
            "ok": False,
            "error": "Layer scale range is not writable: {0}".format(exc),
            "saved": False
        }

    arcpy.RefreshActiveView()
    return {
        "ok": True,
        "data_frame": df.name,
        "layer_name": lyr.name,
        "old_min_scale": old_min,
        "old_max_scale": old_max,
        "min_scale": _safe_get(lyr, "minScale", min_scale),
        "max_scale": _safe_get(lyr, "maxScale", max_scale),
        "saved": False
    }


@action("add_temporary_layer")
def add_temporary_layer(command):
    blocked = require_live_write()
    if blocked:
        return blocked

    path = command.get("path", "")
    if not _path_exists(path):
        return {
            "ok": False,
            "error": "Layer path does not exist: {0}".format(path),
            "saved": False
        }

    position = (command.get("position", "AUTO_ARRANGE") or "AUTO_ARRANGE").upper()
    if position not in ("TOP", "BOTTOM", "AUTO_ARRANGE"):
        return {
            "ok": False,
            "error": "position must be TOP, BOTTOM, or AUTO_ARRANGE",
            "saved": False
        }

    mxd = get_mxd()
    df = get_dataframe(mxd, command.get("data_frame", ""))

    token = str(uuid.uuid4())
    temp_name = "ZAGENT_TEMP_{0}".format(token.replace("-", "")[:10].upper())

    source_layer = arcpy.mapping.Layer(path)
    try:
        source_layer.name = temp_name
    except Exception:
        pass

    arcpy.mapping.AddLayer(df, source_layer, position)
    arcpy.RefreshTOC()
    arcpy.RefreshActiveView()

    matches = find_layer(mxd, temp_name, df.name)
    if not matches:
        # Fallback: identify newest same-source layer and give it the unique name.
        candidates = []
        for lyr in arcpy.mapping.ListLayers(mxd, "", df):
            if safe_layer_source(lyr) == path:
                candidates.append(lyr)
        if candidates:
            live_lyr = candidates[-1]
            try:
                live_lyr.name = temp_name
            except Exception:
                pass
            matches = find_layer(mxd, temp_name, df.name)

    if not matches:
        return {
            "ok": False,
            "error": "Temporary layer was added but could not be resolved safely.",
            "token": token,
            "saved": False
        }

    _TEMP_LAYERS[token] = {
        "data_frame": df.name,
        "layer_name": temp_name,
        "path": path
    }

    return {
        "ok": True,
        "token": token,
        "data_frame": df.name,
        "layer_name": temp_name,
        "path": path,
        "position": position,
        "saved": False
    }


@action("list_temporary_layers")
def list_temporary_layers(command):
    mxd = get_mxd()
    rows = []
    for token in sorted(_TEMP_LAYERS.keys()):
        state = _TEMP_LAYERS[token]
        matches = find_layer(
            mxd,
            state.get("layer_name", ""),
            state.get("data_frame", "")
        )
        rows.append({
            "token": token,
            "data_frame": state.get("data_frame", ""),
            "layer_name": state.get("layer_name", ""),
            "path": state.get("path", ""),
            "present": bool(matches)
        })

    return {
        "ok": True,
        "count": len(rows),
        "temporary_layers": rows,
        "saved": False
    }


@action("remove_temporary_layer")
def remove_temporary_layer(command):
    blocked = require_live_write()
    if blocked:
        return blocked

    token = command.get("token", "")
    state = _TEMP_LAYERS.get(token)
    if state is None:
        return {
            "ok": False,
            "error": "Unknown temporary layer token. Generic layer removal remains blocked.",
            "saved": False
        }

    mxd = get_mxd()
    matches = find_layer(
        mxd,
        state.get("layer_name", ""),
        state.get("data_frame", "")
    )

    if len(matches) > 1:
        return {
            "ok": False,
            "error": "Temporary layer identity became ambiguous; refusing cleanup.",
            "token": token,
            "saved": False
        }

    if matches:
        df, lyr = matches[0]
        arcpy.mapping.RemoveLayer(df, lyr)
        arcpy.RefreshTOC()
        arcpy.RefreshActiveView()

    try:
        del _TEMP_LAYERS[token]
    except Exception:
        pass

    return {
        "ok": True,
        "token": token,
        "removed": bool(matches),
        "layer_name": state.get("layer_name", ""),
        "data_frame": state.get("data_frame", ""),
        "saved": False
    }

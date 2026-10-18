# -*- coding: utf-8 -*-
from __future__ import print_function

import os
import arcpy

from core.registry import action
from core.current_map import get_mxd, find_layer, safe_layer_source
from core.safety import require_live_write, require_geoprocessing
from core.path_guard import guard_manual_write
from core.config import AGENT


def _single_layer(mxd, layer_name, data_frame=""):
    matches = find_layer(mxd, layer_name, data_frame)
    if not matches:
        raise RuntimeError("Layer not found: {0}".format(layer_name))
    if len(matches) != 1:
        raise RuntimeError("Layer is ambiguous: {0}".format(layer_name))
    return matches[0]


def _layer_objects(mxd, names, data_frame=""):
    rows = []
    for name in names:
        rows.append(_single_layer(mxd, name, data_frame)[1])
    return rows


def _validate_output(path):
    blocked = guard_manual_write(path, "output_path")
    if blocked:
        return blocked
    folder = os.path.dirname(path)
    return {
        "ok": True,
        "output_path": path,
        "parent_exists": bool(folder and os.path.isdir(folder)),
        "output_exists": bool(path and arcpy.Exists(path))
    }


@action("gp_preflight")
def gp_preflight(command):
    operation = (command.get("operation", "") or "").lower()
    supported = [
        "buffer", "clip", "dissolve", "intersect", "spatial_join", "near",
        "project", "merge", "union", "erase", "create_file_gdb"
    ]
    if operation not in supported:
        return {
            "ok": False,
            "error": "Unsupported operation for preflight: {0}".format(operation),
            "supported": supported,
            "saved": False
        }

    mxd = get_mxd()
    layer_rows = []
    for name in command.get("layers", []) or []:
        try:
            df, lyr = _single_layer(mxd, name, command.get("data_frame", ""))
            layer_rows.append({
                "name": name,
                "found": True,
                "data_frame": df.name,
                "data_source": safe_layer_source(lyr)
            })
        except Exception as exc:
            layer_rows.append({"name": name, "found": False, "error": str(exc)})

    output_path = command.get("output_path", "") or ""
    output_check = None
    if output_path:
        output_check = _validate_output(output_path)

    missing = [row for row in layer_rows if not row.get("found")]
    path_blocked = bool(output_check and output_check.get("blocked"))
    allow_gp = bool(AGENT.get("allow_geoprocessing", False))

    return {
        "ok": not missing and not path_blocked,
        "operation": operation,
        "layers": layer_rows,
        "output": output_check,
        "allow_geoprocessing": allow_gp,
        "would_be_blocked_by_safe_mode": not allow_gp,
        "ready_if_enabled": not missing and not path_blocked,
        "saved": False
    }


@action("select_by_location")
def select_by_location(command):
    blocked = require_live_write()
    if blocked:
        return blocked

    mxd = get_mxd()
    df, target = _single_layer(
        mxd, command.get("target_layer", ""), command.get("data_frame", ""))
    _, selector = _single_layer(
        mxd, command.get("select_layer", ""), df.name)

    overlap_type = command.get("overlap_type", "INTERSECT") or "INTERSECT"
    search_distance = command.get("search_distance", "") or ""
    selection_type = command.get("selection_type", "NEW_SELECTION") or "NEW_SELECTION"

    arcpy.SelectLayerByLocation_management(
        target, overlap_type, selector, search_distance, selection_type)
    try:
        selected = sorted([int(v) for v in (target.getSelectionSet() or [])])
    except Exception:
        selected = []

    arcpy.RefreshActiveView()
    return {
        "ok": True,
        "data_frame": df.name,
        "target_layer": target.name,
        "select_layer": selector.name,
        "overlap_type": overlap_type,
        "selection_count": len(selected),
        "selected_oids": selected,
        "saved": False
    }


@action("project_features")
def project_features(command):
    blocked = require_geoprocessing()
    if blocked:
        return blocked

    mxd = get_mxd()
    _, inp = _single_layer(
        mxd, command.get("layer_name", ""), command.get("data_frame", ""))
    out = command.get("output_path", "")
    blocked = guard_manual_write(out, "output_path")
    if blocked:
        return blocked

    target_sr = command.get("target_spatial_reference", "")
    if target_sr is None or target_sr == "":
        return {"ok": False, "error": "target_spatial_reference is required"}
    try:
        text = str(target_sr)
        sr = arcpy.SpatialReference(int(text)) if text.isdigit() else arcpy.SpatialReference(text)
    except Exception as exc:
        return {"ok": False, "error": "Invalid spatial reference: {0}".format(exc)}

    arcpy.Project_management(inp, out, sr)
    return {"ok": True, "output_path": out, "saved": False}


@action("merge_layers")
def merge_layers(command):
    blocked = require_geoprocessing()
    if blocked:
        return blocked

    names = command.get("layers", []) or []
    if len(names) < 2:
        return {"ok": False, "error": "At least two layers are required"}
    out = command.get("output_path", "")
    blocked = guard_manual_write(out, "output_path")
    if blocked:
        return blocked

    mxd = get_mxd()
    layers = _layer_objects(mxd, names, command.get("data_frame", ""))
    arcpy.Merge_management(layers, out)
    return {"ok": True, "output_path": out, "saved": False}


@action("union_layers")
def union_layers(command):
    blocked = require_geoprocessing()
    if blocked:
        return blocked

    names = command.get("layers", []) or []
    if len(names) < 2:
        return {"ok": False, "error": "At least two layers are required"}
    out = command.get("output_path", "")
    blocked = guard_manual_write(out, "output_path")
    if blocked:
        return blocked

    mxd = get_mxd()
    layers = _layer_objects(mxd, names, command.get("data_frame", ""))
    arcpy.Union_analysis(
        layers, out,
        command.get("join_attributes", "ALL") or "ALL",
        command.get("cluster_tolerance", "") or "",
        command.get("gaps", "GAPS") or "GAPS")
    return {"ok": True, "output_path": out, "saved": False}


@action("erase_features")
def erase_features(command):
    blocked = require_geoprocessing()
    if blocked:
        return blocked

    out = command.get("output_path", "")
    blocked = guard_manual_write(out, "output_path")
    if blocked:
        return blocked

    mxd = get_mxd()
    _, inp = _single_layer(
        mxd, command.get("input_layer", ""), command.get("data_frame", ""))
    _, erase = _single_layer(
        mxd, command.get("erase_layer", ""), command.get("data_frame", ""))
    arcpy.Erase_analysis(inp, erase, out)
    return {"ok": True, "output_path": out, "saved": False}


@action("create_file_gdb")
def create_file_gdb(command):
    blocked = require_geoprocessing()
    if blocked:
        return blocked

    out_folder = command.get("out_folder", "")
    gdb_name = command.get("gdb_name", "")
    if not out_folder or not gdb_name:
        return {"ok": False, "error": "out_folder and gdb_name are required"}
    if not gdb_name.lower().endswith(".gdb"):
        gdb_name += ".gdb"
    full = os.path.join(out_folder, gdb_name)
    blocked = guard_manual_write(full, "output_path")
    if blocked:
        return blocked
    if not os.path.isdir(out_folder):
        os.makedirs(out_folder)
    arcpy.CreateFileGDB_management(
        out_folder, gdb_name,
        command.get("version", "CURRENT") or "CURRENT")
    return {"ok": True, "output_path": full, "saved": False}

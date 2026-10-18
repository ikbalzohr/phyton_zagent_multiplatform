# -*- coding: utf-8 -*-
import arcpy
from core.registry import action
from core.safety import require_geoprocessing, require_destructive
from core.current_map import get_mxd, find_layer
from core.path_guard import guard_manual_write

def _layer(name, df=""):
    mxd = get_mxd()
    matches = find_layer(mxd, name, df)
    if not matches:
        raise RuntimeError("Layer not found: {0}".format(name))
    return matches[0][1]

@action("spatial_join")
def spatial_join(command):
    blocked = require_geoprocessing()
    if blocked:
        return blocked
    target = _layer(command.get("target_layer", ""), command.get("data_frame", ""))
    join = _layer(command.get("join_layer", ""), command.get("data_frame", ""))
    out = command.get("output_path", "")
    blocked = guard_manual_write(out, "output_path")
    if blocked:
        return blocked
    arcpy.SpatialJoin_analysis(target, join, out,
                               command.get("join_operation", "JOIN_ONE_TO_ONE"),
                               command.get("join_type", "KEEP_ALL"),
                               "",
                               command.get("match_option", "INTERSECT"))
    return {"ok": True, "output_path": out}

@action("near")
def near(command):
    blocked = require_geoprocessing()
    if blocked:
        return blocked
    blocked = require_destructive()
    if blocked:
        return blocked
    inp = _layer(command.get("input_layer", ""), command.get("data_frame", ""))
    near_lyr = _layer(command.get("near_layer", ""), command.get("data_frame", ""))
    arcpy.Near_analysis(inp, near_lyr, command.get("search_radius", ""),
                        command.get("location", "NO_LOCATION"),
                        command.get("angle", "NO_ANGLE"),
                        command.get("method", "PLANAR"))
    return {"ok": True, "input_layer": command.get("input_layer", "")}

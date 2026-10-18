# -*- coding: utf-8 -*-
import arcpy
from core.registry import action
from core.safety import require_geoprocessing
from core.current_map import get_mxd, find_layer
from core.path_guard import guard_manual_write

def _layer(name, df=""):
    mxd = get_mxd()
    matches = find_layer(mxd, name, df)
    if not matches:
        raise RuntimeError("Layer not found: {0}".format(name))
    return matches[0][1]

@action("buffer")
def buffer(command):
    blocked = require_geoprocessing()
    if blocked:
        return blocked
    inp = _layer(command.get("layer_name", ""), command.get("data_frame", ""))
    out = command.get("output_path", "")
    blocked = guard_manual_write(out, "output_path")
    if blocked:
        return blocked
    distance = command.get("distance", "")
    arcpy.Buffer_analysis(inp, out, distance, command.get("line_side", "FULL"),
                          command.get("line_end_type", "ROUND"),
                          command.get("dissolve_option", "NONE"),
                          command.get("dissolve_field", ""))
    return {"ok": True, "output_path": out}

@action("clip")
def clip(command):
    blocked = require_geoprocessing()
    if blocked:
        return blocked
    inp = _layer(command.get("input_layer", ""), command.get("data_frame", ""))
    clip_lyr = _layer(command.get("clip_layer", ""), command.get("data_frame", ""))
    out = command.get("output_path", "")
    blocked = guard_manual_write(out, "output_path")
    if blocked:
        return blocked
    arcpy.Clip_analysis(inp, clip_lyr, out)
    return {"ok": True, "output_path": out}

@action("dissolve")
def dissolve(command):
    blocked = require_geoprocessing()
    if blocked:
        return blocked
    inp = _layer(command.get("layer_name", ""), command.get("data_frame", ""))
    out = command.get("output_path", "")
    blocked = guard_manual_write(out, "output_path")
    if blocked:
        return blocked
    fields = command.get("dissolve_fields", [])
    arcpy.Dissolve_management(inp, out, fields)
    return {"ok": True, "output_path": out}

@action("intersect")
def intersect(command):
    blocked = require_geoprocessing()
    if blocked:
        return blocked
    names = command.get("layers", [])
    layers = [_layer(n, command.get("data_frame", "")) for n in names]
    out = command.get("output_path", "")
    blocked = guard_manual_write(out, "output_path")
    if blocked:
        return blocked
    arcpy.Intersect_analysis(layers, out, command.get("join_attributes", "ALL"),
                             command.get("cluster_tolerance", ""),
                             command.get("output_type", "INPUT"))
    return {"ok": True, "output_path": out}

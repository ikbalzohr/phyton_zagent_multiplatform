# -*- coding: utf-8 -*-
import arcpy
from core.registry import action
from core.current_map import get_mxd, find_layer, safe_layer_source
from core.safety import require_live_write

@action("list_layers")
def list_layers(command):
    mxd = get_mxd()
    rows = []
    for df in arcpy.mapping.ListDataFrames(mxd):
        for lyr in arcpy.mapping.ListLayers(mxd, "", df):
            rows.append({
                "name": lyr.name,
                "data_frame": df.name,
                "visible": getattr(lyr, "visible", None),
                "data_source": safe_layer_source(lyr),
                "is_group_layer": bool(getattr(lyr, "isGroupLayer", False))
            })
    return {"ok": True, "layers": rows}

@action("set_layer_visibility")
def set_layer_visibility(command):
    blocked = require_live_write()
    if blocked:
        return blocked
    name = command.get("layer_name", "")
    visible = bool(command.get("visible", False))
    df_name = command.get("data_frame", "")
    if not name:
        return {"ok": False, "error": "layer_name is required"}
    mxd = get_mxd()
    matches = find_layer(mxd, name, df_name)
    if not matches:
        return {"ok": False, "error": "Layer not found: {0}".format(name)}
    changed = []
    for df, lyr in matches:
        lyr.visible = visible
        changed.append({"name": lyr.name, "data_frame": df.name, "visible": lyr.visible})
    arcpy.RefreshActiveView()
    arcpy.RefreshTOC()
    return {"ok": True, "matches": changed, "saved": False}

@action("set_definition_query")
def set_definition_query(command):
    blocked = require_live_write()
    if blocked:
        return blocked
    name = command.get("layer_name", "")
    query = command.get("definition_query", "")
    mxd = get_mxd()
    matches = find_layer(mxd, name, command.get("data_frame", ""))
    if not matches:
        return {"ok": False, "error": "Layer not found: {0}".format(name)}
    changed = []
    for df, lyr in matches:
        if not lyr.supports("DEFINITIONQUERY"):
            continue
        lyr.definitionQuery = query
        changed.append({"name": lyr.name, "data_frame": df.name, "definition_query": query})
    arcpy.RefreshActiveView()
    arcpy.RefreshTOC()
    return {"ok": bool(changed), "matches": changed, "saved": False}

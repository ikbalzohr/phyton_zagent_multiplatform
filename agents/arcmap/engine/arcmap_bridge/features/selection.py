# -*- coding: utf-8 -*-
import arcpy
from core.registry import action
from core.current_map import get_mxd, find_layer
from core.safety import require_live_write

@action("select_by_attribute")
def select_by_attribute(command):
    blocked = require_live_write()
    if blocked:
        return blocked
    name = command.get("layer_name", "")
    where = command.get("where_clause", "")
    selection_type = command.get("selection_type", "NEW_SELECTION")
    mxd = get_mxd()
    matches = find_layer(mxd, name, command.get("data_frame", ""))
    if not matches:
        return {"ok": False, "error": "Layer not found: {0}".format(name)}
    for df, lyr in matches:
        arcpy.SelectLayerByAttribute_management(lyr, selection_type, where)
    arcpy.RefreshActiveView()
    return {"ok": True, "layer_name": name, "saved": False}

@action("clear_selection")
def clear_selection(command):
    blocked = require_live_write()
    if blocked:
        return blocked
    name = command.get("layer_name", "")
    mxd = get_mxd()
    matches = find_layer(mxd, name, command.get("data_frame", ""))
    for df, lyr in matches:
        arcpy.SelectLayerByAttribute_management(lyr, "CLEAR_SELECTION")
    arcpy.RefreshActiveView()
    return {"ok": bool(matches), "layer_name": name, "saved": False}

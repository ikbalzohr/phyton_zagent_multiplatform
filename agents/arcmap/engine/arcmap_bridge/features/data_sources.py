# -*- coding: utf-8 -*-
import os
import arcpy
from core.registry import action
from core.current_map import get_mxd, get_dataframe, find_layer
from core.safety import require_live_write, require_destructive

@action("add_layer")
def add_layer(command):
    blocked = require_live_write()
    if blocked:
        return blocked
    path = command.get("path", "")
    if not path or not os.path.exists(path):
        return {"ok": False, "error": "Layer path does not exist: {0}".format(path)}
    mxd = get_mxd()
    df = get_dataframe(mxd, command.get("data_frame", ""))
    lyr = arcpy.mapping.Layer(path)
    arcpy.mapping.AddLayer(df, lyr, command.get("position", "AUTO_ARRANGE"))
    arcpy.RefreshTOC()
    arcpy.RefreshActiveView()
    return {"ok": True, "layer_name": lyr.name, "data_frame": df.name, "saved": False}

@action("remove_layer")
def remove_layer(command):
    blocked = require_destructive()
    if blocked:
        return blocked
    name = command.get("layer_name", "")
    mxd = get_mxd()
    matches = find_layer(mxd, name, command.get("data_frame", ""))
    if not matches:
        return {"ok": False, "error": "Layer not found: {0}".format(name)}
    removed = []
    for df, lyr in matches:
        arcpy.mapping.RemoveLayer(df, lyr)
        removed.append({"name": name, "data_frame": df.name})
    arcpy.RefreshTOC()
    arcpy.RefreshActiveView()
    return {"ok": True, "removed": removed, "saved": False}

@action("replace_data_source")
def replace_data_source(command):
    blocked = require_live_write()
    if blocked:
        return blocked
    name = command.get("layer_name", "")
    workspace_path = command.get("workspace_path", "")
    workspace_type = command.get("workspace_type", "")
    dataset_name = command.get("dataset_name", "")
    validate = bool(command.get("validate", True))
    mxd = get_mxd()
    matches = find_layer(mxd, name, command.get("data_frame", ""))
    if not matches:
        return {"ok": False, "error": "Layer not found: {0}".format(name)}
    changed = []
    for df, lyr in matches:
        lyr.replaceDataSource(workspace_path, workspace_type, dataset_name, validate)
        changed.append({"name": lyr.name, "data_source": getattr(lyr, "dataSource", "")})
    arcpy.RefreshTOC()
    arcpy.RefreshActiveView()
    return {"ok": True, "matches": changed, "saved": False}

# -*- coding: utf-8 -*-
import arcpy
from core.registry import action
from core.current_map import get_mxd, find_layer
from core.safety import require_live_write

@action("apply_symbology_from_layer")
def apply_symbology_from_layer(command):
    blocked = require_live_write()
    if blocked:
        return blocked
    name = command.get("layer_name", "")
    source = command.get("source_layer_file", "")
    if not source:
        return {"ok": False, "error": "source_layer_file is required"}
    mxd = get_mxd()
    matches = find_layer(mxd, name, command.get("data_frame", ""))
    if not matches:
        return {"ok": False, "error": "Layer not found: {0}".format(name)}
    changed = []
    for df, lyr in matches:
        arcpy.ApplySymbologyFromLayer_management(lyr, source)
        changed.append({"name": lyr.name, "source_layer_file": source})
    arcpy.RefreshActiveView()
    arcpy.RefreshTOC()
    return {"ok": True, "matches": changed, "saved": False}

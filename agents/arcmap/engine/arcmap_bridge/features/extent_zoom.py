# -*- coding: utf-8 -*-
import arcpy
from core.registry import action
from core.current_map import get_mxd, find_layer, get_dataframe
from core.safety import require_live_write

@action("zoom_to_layer")
def zoom_to_layer(command):
    blocked = require_live_write()
    if blocked:
        return blocked
    name = command.get("layer_name", "")
    mxd = get_mxd()
    matches = find_layer(mxd, name, command.get("data_frame", ""))
    if not matches:
        return {"ok": False, "error": "Layer not found: {0}".format(name)}
    df, lyr = matches[0]
    df.extent = lyr.getExtent()
    if command.get("scale_factor"):
        try:
            df.scale = float(df.scale) * float(command["scale_factor"])
        except Exception:
            pass
    arcpy.RefreshActiveView()
    return {"ok": True, "layer_name": name, "scale": df.scale, "saved": False}

@action("set_map_scale")
def set_map_scale(command):
    blocked = require_live_write()
    if blocked:
        return blocked
    scale = float(command.get("scale"))
    mxd = get_mxd()
    df = get_dataframe(mxd, command.get("data_frame", ""))
    df.scale = scale
    arcpy.RefreshActiveView()
    return {"ok": True, "data_frame": df.name, "scale": df.scale, "saved": False}

# -*- coding: utf-8 -*-
import arcpy
from core.registry import action
from core.current_map import get_mxd, find_layer
from core.safety import require_live_write

@action("toggle_labels")
def toggle_labels(command):
    blocked = require_live_write()
    if blocked:
        return blocked
    name = command.get("layer_name", "")
    show = bool(command.get("show", True))
    mxd = get_mxd()
    matches = find_layer(mxd, name, command.get("data_frame", ""))
    changed = []
    for df, lyr in matches:
        if lyr.supports("SHOWLABELS"):
            lyr.showLabels = show
            changed.append({"name": lyr.name, "show": show})
    arcpy.RefreshActiveView()
    return {"ok": bool(changed), "matches": changed, "saved": False}

@action("set_label_expression")
def set_label_expression(command):
    blocked = require_live_write()
    if blocked:
        return blocked
    name = command.get("layer_name", "")
    expression = command.get("expression", "")
    parser = command.get("expression_parser", "PYTHON")
    mxd = get_mxd()
    matches = find_layer(mxd, name, command.get("data_frame", ""))
    changed = []
    for df, lyr in matches:
        if not lyr.supports("LABELCLASSES"):
            continue
        classes = lyr.labelClasses
        if not classes:
            continue
        classes[0].expression = expression
        try:
            classes[0].expressionParser = parser
        except Exception:
            pass
        lyr.showLabels = True
        changed.append({"name": lyr.name, "expression": expression})
    arcpy.RefreshActiveView()
    return {"ok": bool(changed), "matches": changed, "saved": False}

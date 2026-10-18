# -*- coding: utf-8 -*-
import arcpy
from core.registry import action
from core.current_map import get_mxd
from core.safety import require_live_write

@action("list_layout_elements")
def list_layout_elements(command):
    mxd = get_mxd()
    rows = []
    for el in arcpy.mapping.ListLayoutElements(mxd):
        rows.append({
            "name": getattr(el, "name", ""),
            "type": getattr(el, "type", ""),
            "x": getattr(el, "elementPositionX", None),
            "y": getattr(el, "elementPositionY", None),
            "width": getattr(el, "elementWidth", None),
            "height": getattr(el, "elementHeight", None)
        })
    return {"ok": True, "elements": rows}

@action("set_layout_element_position")
def set_layout_element_position(command):
    blocked = require_live_write()
    if blocked:
        return blocked
    name = command.get("element_name", "")
    mxd = get_mxd()
    matches = [el for el in arcpy.mapping.ListLayoutElements(mxd) if getattr(el, "name", "") == name]
    if not matches:
        return {"ok": False, "error": "Layout element not found: {0}".format(name)}
    el = matches[0]
    if command.get("x") is not None:
        el.elementPositionX = float(command["x"])
    if command.get("y") is not None:
        el.elementPositionY = float(command["y"])
    if command.get("width") is not None and hasattr(el, "elementWidth"):
        el.elementWidth = float(command["width"])
    if command.get("height") is not None and hasattr(el, "elementHeight"):
        el.elementHeight = float(command["height"])
    arcpy.RefreshActiveView()
    return {"ok": True, "element_name": name, "saved": False}

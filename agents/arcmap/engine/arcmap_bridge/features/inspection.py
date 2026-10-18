# -*- coding: utf-8 -*-
import os
import datetime
import arcpy
from core.registry import action
from core.current_map import get_mxd, safe_layer_source
from core.bridge_state import context

def safe_get(obj, name, warnings, default=None, scope=""):
    try:
        return getattr(obj, name)
    except Exception as exc:
        warnings.append({"field": (scope + "." if scope else "") + name,
                         "message": str(exc)})
        return default

def state_snapshot(command):
    mxd = get_mxd()  # Critical failure: cannot inspect a different map.
    warnings = []
    frames = []
    active = safe_get(mxd, "activeDataFrame", warnings)
    active_name = safe_get(active, "name", warnings) if active else None
    try:
        dataframes = arcpy.mapping.ListDataFrames(mxd)
    except Exception as exc:
        return {"ok": False, "code": "DATAFRAMES_UNAVAILABLE", "error": str(exc)}
    for df in dataframes:
        name = safe_get(df, "name", warnings, "", "dataframe")
        rows = []
        try:
            layers = arcpy.mapping.ListLayers(mxd, "", df)
        except Exception as exc:
            warnings.append({"field": name + ".layers", "message": str(exc)})
            layers = []
        for lyr in layers:
            rows.append({"name": safe_get(lyr, "name", warnings, "", name),
                         "visible": safe_get(lyr, "visible", warnings, None, name),
                         "data_source": safe_layer_source(lyr),
                         "is_group_layer": safe_get(lyr, "isGroupLayer", warnings, False, name)})
        ext = safe_get(df, "extent", warnings, None, name)
        extent = {k: safe_get(ext, k, warnings, None, name + ".extent")
                  for k in ("XMin", "YMin", "XMax", "YMax")} if ext else None
        frames.append({"name": name, "scale": safe_get(df, "scale", warnings, None, name),
                       "extent": extent, "layers": rows})
    path = safe_get(mxd, "filePath", warnings, "")
    page = safe_get(mxd, "pageSize", warnings)
    page_size = None
    if page is not None:
        try:
            page_size = {"width": page.width, "height": page.height}
        except Exception:
            try:
                page_size = {"width": page[0], "height": page[1]}
            except Exception as exc:
                warnings.append({"field": "page_size", "message": str(exc)})
    view = safe_get(mxd, "activeView", warnings)
    current = next((f for f in frames if f["name"] == active_name), {})
    correlation = command.get("correlation") or {}
    return {"ok": True, "partial": bool(warnings), "schema_version": 1,
            "mxd": path, "document_path": path, "document_name": os.path.basename(path),
            "document_title": safe_get(mxd, "title", warnings, ""),
            "active_dataframe": active_name, "scale": current.get("scale"),
            "extent": current.get("extent"), "frames": frames,
            "layers": current.get("layers", []), "selected_layers": None,
            "selection_scope": "TOC selection unavailable through ArcPy",
            "layout_mode": view == "PAGE_LAYOUT" if view is not None else None,
            "page_size": page_size,
            "data_sources": [l["data_source"] for f in frames for l in f["layers"]],
            "warnings": warnings, "timestamp": datetime.datetime.utcnow().isoformat() + "Z",
            "context": context(mxd), "session_id": correlation.get("session_id"),
            "request_id": correlation.get("request_id"), "trace_id": correlation.get("trace_id"),
            "device_id": correlation.get("device_id"), "saved": False}

@action("inspect_current_map")
def inspect_current_map(command):
    return state_snapshot(command)

@action("list_layout_text")
def list_layout_text(command):
    mxd = get_mxd()
    warnings = []
    rows = []
    for i, el in enumerate(arcpy.mapping.ListLayoutElements(mxd, "TEXT_ELEMENT")):
        row = {"index": i}
        for output, attribute in (("name", "name"), ("text", "text"),
                                  ("font_size", "fontSize"), ("x", "elementPositionX"),
                                  ("y", "elementPositionY")):
            row[output] = safe_get(el, attribute, warnings, None, str(i))
        rows.append(row)
    return {"ok": True, "elements": rows, "warnings": warnings, "partial": bool(warnings)}

# -*- coding: utf-8 -*-
from __future__ import print_function

import math
import arcpy

from core.registry import action, names as action_names
from core.current_map import get_mxd, find_layer, safe_layer_source
from core.config import AGENT


def _safe_get(obj, name, default=None):
    try:
        return getattr(obj, name)
    except Exception:
        return default


def _single_layer(mxd, layer_name, data_frame=""):
    matches = find_layer(mxd, layer_name, data_frame)
    if not matches:
        raise RuntimeError("Layer not found: {0}".format(layer_name))
    if len(matches) != 1:
        raise RuntimeError("Layer is ambiguous: {0}".format(layer_name))
    return matches[0]


def _json_value(value):
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    try:
        unicode_type = unicode
    except NameError:
        unicode_type = str
    if isinstance(value, unicode_type):
        return value
    try:
        if hasattr(value, "isoformat"):
            return value.isoformat()
    except Exception:
        pass
    try:
        return str(value)
    except Exception:
        return None


def _field_map(lyr):
    try:
        fields = arcpy.ListFields(lyr)
    except Exception:
        fields = arcpy.ListFields(safe_layer_source(lyr))
    return dict((f.name, f) for f in fields)


def _extent(lyr):
    try:
        return lyr.getExtent()
    except Exception:
        source = safe_layer_source(lyr)
        if source:
            return arcpy.Describe(source).extent
        return None


@action("get_feature_count")
def get_feature_count(command):
    mxd = get_mxd()
    df, lyr = _single_layer(
        mxd, command.get("layer_name", ""), command.get("data_frame", ""))
    where_clause = command.get("where_clause", "") or ""
    count = 0
    with arcpy.da.SearchCursor(lyr, ["OID@"], where_clause) as cursor:
        for row in cursor:
            count += 1
    return {
        "ok": True,
        "data_frame": df.name,
        "layer_name": lyr.name,
        "where_clause": where_clause,
        "count": count,
        "saved": False
    }


@action("get_unique_values")
def get_unique_values(command):
    mxd = get_mxd()
    df, lyr = _single_layer(
        mxd, command.get("layer_name", ""), command.get("data_frame", ""))
    field_name = command.get("field_name", "")
    fields = _field_map(lyr)
    if field_name not in fields:
        return {"ok": False, "error": "Field not found: {0}".format(field_name), "saved": False}

    limit = max(1, min(int(command.get("limit", 100)), 500))
    where_clause = command.get("where_clause", "") or ""
    values = []
    seen = set()
    truncated = False
    with arcpy.da.SearchCursor(lyr, [field_name], where_clause) as cursor:
        for row in cursor:
            value = _json_value(row[0])
            key = repr(value)
            if key in seen:
                continue
            seen.add(key)
            if len(values) >= limit:
                truncated = True
                break
            values.append(value)

    try:
        values = sorted(values, key=lambda item: (item is None, str(item)))
    except Exception:
        pass
    return {
        "ok": True,
        "data_frame": df.name,
        "layer_name": lyr.name,
        "field_name": field_name,
        "values": values,
        "unique_count_returned": len(values),
        "truncated": truncated,
        "limit": limit,
        "saved": False
    }


@action("get_field_statistics")
def get_field_statistics(command):
    mxd = get_mxd()
    df, lyr = _single_layer(
        mxd, command.get("layer_name", ""), command.get("data_frame", ""))
    field_name = command.get("field_name", "")
    fields = _field_map(lyr)
    field = fields.get(field_name)
    if field is None:
        return {"ok": False, "error": "Field not found: {0}".format(field_name), "saved": False}

    numeric_types = set(["SmallInteger", "Integer", "Single", "Double"])
    if field.type not in numeric_types:
        return {
            "ok": False,
            "error": "Field is not numeric: {0} ({1})".format(field_name, field.type),
            "saved": False
        }

    max_rows = max(1, min(int(command.get("max_rows", 100000)), 1000000))
    where_clause = command.get("where_clause", "") or ""
    count = 0
    null_count = 0
    total = 0.0
    min_value = None
    max_value = None
    truncated = False

    with arcpy.da.SearchCursor(lyr, [field_name], where_clause) as cursor:
        for row in cursor:
            if count + null_count >= max_rows:
                truncated = True
                break
            value = row[0]
            if value is None:
                null_count += 1
                continue
            value = float(value)
            count += 1
            total += value
            min_value = value if min_value is None or value < min_value else min_value
            max_value = value if max_value is None or value > max_value else max_value

    mean = (total / count) if count else None
    return {
        "ok": True,
        "data_frame": df.name,
        "layer_name": lyr.name,
        "field_name": field_name,
        "where_clause": where_clause,
        "count": count,
        "null_count": null_count,
        "min": min_value,
        "max": max_value,
        "sum": total if count else None,
        "mean": mean,
        "truncated": truncated,
        "max_rows": max_rows,
        "saved": False
    }


@action("query_features")
def query_features(command):
    mxd = get_mxd()
    df, lyr = _single_layer(
        mxd, command.get("layer_name", ""), command.get("data_frame", ""))
    requested = command.get("fields", []) or []
    field_map = _field_map(lyr)
    if not requested:
        requested = [name for name in field_map.keys() if field_map[name].type != "Geometry"][:10]
    missing = [name for name in requested if name not in field_map]
    if missing:
        return {"ok": False, "error": "Fields not found: {0}".format(", ".join(missing)), "saved": False}

    limit = max(1, min(int(command.get("limit", 50)), 500))
    include_geometry = bool(command.get("include_geometry", False))
    cursor_fields = list(requested)
    if include_geometry:
        cursor_fields.append("SHAPE@")
    where_clause = command.get("where_clause", "") or ""

    rows = []
    with arcpy.da.SearchCursor(lyr, cursor_fields, where_clause) as cursor:
        for row in cursor:
            item = {}
            for index, name in enumerate(requested):
                item[name] = _json_value(row[index])
            if include_geometry:
                geom = row[-1]
                geom_info = None
                if geom is not None:
                    try:
                        c = geom.centroid
                        ext = geom.extent
                        geom_info = {
                            "centroid": {"x": float(c.X), "y": float(c.Y)},
                            "extent": {
                                "xmin": float(ext.XMin), "ymin": float(ext.YMin),
                                "xmax": float(ext.XMax), "ymax": float(ext.YMax)
                            }
                        }
                    except Exception:
                        geom_info = None
                item["_geometry"] = geom_info
            rows.append(item)
            if len(rows) >= limit:
                break

    return {
        "ok": True,
        "data_frame": df.name,
        "layer_name": lyr.name,
        "fields": requested,
        "where_clause": where_clause,
        "row_count": len(rows),
        "limit": limit,
        "rows": rows,
        "saved": False
    }


@action("get_geometry_summary")
def get_geometry_summary(command):
    mxd = get_mxd()
    df, lyr = _single_layer(
        mxd, command.get("layer_name", ""), command.get("data_frame", ""))
    max_features = max(1, min(int(command.get("max_features", 100000)), 1000000))
    where_clause = command.get("where_clause", "") or ""

    count = 0
    null_geometry = 0
    total_area = 0.0
    total_length = 0.0
    truncated = False
    with arcpy.da.SearchCursor(lyr, ["SHAPE@"], where_clause) as cursor:
        for row in cursor:
            if count + null_geometry >= max_features:
                truncated = True
                break
            geom = row[0]
            if geom is None:
                null_geometry += 1
                continue
            count += 1
            try:
                total_area += float(geom.area)
            except Exception:
                pass
            try:
                total_length += float(geom.length)
            except Exception:
                pass

    desc = arcpy.Describe(lyr)
    ext = _extent(lyr)
    return {
        "ok": True,
        "data_frame": df.name,
        "layer_name": lyr.name,
        "shape_type": _safe_get(desc, "shapeType", None),
        "spatial_reference": _safe_get(_safe_get(desc, "spatialReference", None), "name", None),
        "feature_count_scanned": count,
        "null_geometry_count": null_geometry,
        "total_area_dataset_units": total_area,
        "total_length_dataset_units": total_length,
        "extent": ({
            "xmin": float(ext.XMin), "ymin": float(ext.YMin),
            "xmax": float(ext.XMax), "ymax": float(ext.YMax)
        } if ext is not None else None),
        "truncated": truncated,
        "max_features": max_features,
        "saved": False
    }


@action("compare_layer_extents")
def compare_layer_extents(command):
    mxd = get_mxd()
    df1, lyr1 = _single_layer(
        mxd, command.get("layer_a", ""), command.get("data_frame", ""))
    df2, lyr2 = _single_layer(
        mxd, command.get("layer_b", ""), command.get("data_frame", ""))
    ext1 = _extent(lyr1)
    ext2 = _extent(lyr2)
    if ext1 is None or ext2 is None:
        return {"ok": False, "error": "Layer extent unavailable", "saved": False}

    xmin = max(ext1.XMin, ext2.XMin)
    ymin = max(ext1.YMin, ext2.YMin)
    xmax = min(ext1.XMax, ext2.XMax)
    ymax = min(ext1.YMax, ext2.YMax)
    iw = max(0.0, xmax - xmin)
    ih = max(0.0, ymax - ymin)
    intersection_area = iw * ih
    area1 = max(0.0, ext1.XMax - ext1.XMin) * max(0.0, ext1.YMax - ext1.YMin)
    area2 = max(0.0, ext2.XMax - ext2.XMin) * max(0.0, ext2.YMax - ext2.YMin)

    return {
        "ok": True,
        "layer_a": lyr1.name,
        "layer_b": lyr2.name,
        "same_data_frame": df1.name == df2.name,
        "bbox_intersects": intersection_area > 0,
        "bbox_intersection_area": intersection_area,
        "bbox_overlap_ratio_a": (intersection_area / area1) if area1 else 0.0,
        "bbox_overlap_ratio_b": (intersection_area / area2) if area2 else 0.0,
        "note": "Bounding-box comparison only; not a feature-level overlay.",
        "saved": False
    }


@action("get_agent_context")
def get_agent_context(command):
    mxd = get_mxd()
    frames = []
    for df in arcpy.mapping.ListDataFrames(mxd):
        ext = df.extent
        layers = []
        for index, lyr in enumerate(arcpy.mapping.ListLayers(mxd, "", df)):
            layers.append({
                "index": index,
                "name": lyr.name,
                "visible": _safe_get(lyr, "visible", None),
                "data_source": safe_layer_source(lyr),
                "is_feature_layer": bool(_safe_get(lyr, "isFeatureLayer", False)),
                "is_group_layer": bool(_safe_get(lyr, "isGroupLayer", False)),
                "show_labels": _safe_get(lyr, "showLabels", None),
                "transparency": _safe_get(lyr, "transparency", None)
            })
        frames.append({
            "name": df.name,
            "scale": float(df.scale),
            "extent": {
                "xmin": float(ext.XMin), "ymin": float(ext.YMin),
                "xmax": float(ext.XMax), "ymax": float(ext.YMax)
            },
            "layer_count": len(layers),
            "layers": layers
        })

    broken = []
    try:
        for obj in arcpy.mapping.ListBrokenDataSources(mxd):
            broken.append(_safe_get(obj, "name", "") or "")
    except Exception:
        pass

    layout_count = len(arcpy.mapping.ListLayoutElements(mxd))
    return {
        "ok": True,
        "mxd": _safe_get(mxd, "filePath", "") or "",
        "document_title": _safe_get(mxd, "title", "") or "",
        "frame_count": len(frames),
        "frames": frames,
        "layout_element_count": layout_count,
        "broken_data_sources": broken,
        "ddp_enabled": bool(_safe_get(mxd, "isDDPEnabled", False)),
        "safety": {
            "safe_mode": bool(AGENT.get("safe_mode", True)),
            "allow_live_write": bool(AGENT.get("allow_live_write", True)),
            "allow_save": bool(AGENT.get("allow_save", False)),
            "allow_destructive_operations": bool(AGENT.get("allow_destructive_operations", False)),
            "allow_geoprocessing": bool(AGENT.get("allow_geoprocessing", False)),
            "allow_export": bool(AGENT.get("allow_export", True))
        },
        "saved": False
    }


@action("get_capability_matrix")
def get_capability_matrix(command):
    actions = action_names()
    allow_gp = bool(AGENT.get("allow_geoprocessing", False))
    allow_save = bool(AGENT.get("allow_save", False))
    allow_destructive = bool(AGENT.get("allow_destructive_operations", False))
    levels = [
        {"level": "L0", "name": "Connection", "status": "available"},
        {"level": "L1", "name": "Inspection", "status": "available"},
        {"level": "L2", "name": "Basic Control", "status": "available"},
        {"level": "L2.5", "name": "Observability / Reversible Control", "status": "available"},
        {"level": "L3", "name": "Layer & Data Management", "status": "available"},
        {"level": "L4", "name": "Styling / Symbology / Labels", "status": "available"},
        {"level": "L5", "name": "Geoprocessing / Spatial Analysis",
         "status": "enabled" if allow_gp else "installed_but_locked"},
        {"level": "L6", "name": "Layout Automation", "status": "available"},
        {"level": "L7", "name": "Export / QA", "status": "available"},
        {"level": "L8", "name": "Full Map Generation", "status": "available"},
        {"level": "L9", "name": "GIS Analytical Agent", "status": "available"}
    ]
    return {
        "ok": True,
        "bridge_action_count": len(actions),
        "levels": levels,
        "guards": {
            "save": "enabled" if allow_save else "locked",
            "destructive": "enabled" if allow_destructive else "locked",
            "geoprocessing": "enabled" if allow_gp else "locked"
        },
        "saved": False
    }

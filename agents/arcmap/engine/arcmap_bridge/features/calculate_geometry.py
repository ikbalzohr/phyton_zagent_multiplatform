# -*- coding: utf-8 -*-
"""ARC-09: bulk X/Y calculation with explicit datum/output CRS.

The tool edits feature data (not only the MXD). Requires write, geoprocessing
and destructive permissions plus an explicit per-call confirmation. Updates
to shapefiles are not atomic; callers should make a dataset backup first.
"""
from __future__ import division
import math
import os
import arcpy
from core.registry import action
from core.current_map import get_mxd, find_layer, safe_layer_source
from core.path_guard import guard_manual_write
from core.safety import require_live_write, require_geoprocessing, require_destructive


def _double_field_map(layer):
    return dict((field.name.lower(), field) for field in arcpy.ListFields(layer))


def validate_field_names(x_field, y_field):
    x_field, y_field = str(x_field or ""), str(y_field or "")
    if not x_field or not y_field or x_field.lower() == y_field.lower():
        raise ValueError("Two distinct output field names are required")
    return x_field, y_field


def safe_xy(geometry, out_sr):
    if not geometry:
        return None
    source_sr = getattr(geometry, "spatialReference", None)
    if not source_sr or source_sr.name == "Unknown":
        raise ValueError("Unknown source spatial reference: cannot transform X/Y")
    projected = geometry.projectAs(out_sr)
    point = (projected.firstPoint if projected.type == "point"
             else projected.trueCentroid)
    if point is None:
        return None
    x, y = float(point.X), float(point.Y)
    if math.isnan(x) or math.isnan(y) or math.isinf(x) or math.isinf(y):
        raise ValueError("Non-finite geometry coordinate")
    return (x, y)


@action("calculate_geometry_xy")
def calculate_geometry_xy(command):
    for check in (require_live_write, require_geoprocessing, require_destructive):
        blocked = check()
        if blocked:
            return blocked
    if command.get("confirm_dataset_write") is not True:
        return {"ok": False, "code": "DATASET_WRITE_CONFIRMATION_REQUIRED"}
    layer_name = str(command.get("layer_name") or "")
    matches = find_layer(get_mxd(), layer_name, command.get("data_frame") or "")
    if len(matches) != 1:
        raise RuntimeError("Exactly one existing layer is required")
    df, layer = matches[0]
    source = safe_layer_source(layer)
    if not source or not arcpy.Exists(source):
        raise RuntimeError("Layer source is not an editable local feature dataset")
    blocked = guard_manual_write(source, "layer_source")
    if blocked:
        return blocked
    if str(arcpy.Describe(source).shapeType).upper() not in (
            "POINT", "MULTIPOINT", "POLYGON", "POLYLINE"):
        raise RuntimeError("Unsupported geometry type")
    x_name, y_name = validate_field_names(
        command.get("x_field", "X_DD"), command.get("y_field", "Y_DD"))
    wkid = int(command.get("output_wkid", 4326))
    if wkid <= 0:
        raise ValueError("output_wkid must be a positive CRS code")
    sr = arcpy.SpatialReference(wkid)
    if not sr or sr.name == "Unknown":
        raise ValueError("Unknown output coordinate reference system")
    max_rows = int(command.get("max_rows", 100000))
    if not 1 <= max_rows <= 1000000:
        raise ValueError("max_rows outside the allowed interval")
    # Planning pass rejects malformed geometries before any row is modified.
    coordinates = {}
    with arcpy.da.SearchCursor(layer, ["OID@", "SHAPE@"]) as cursor:
        for oid, shape in cursor:
            if len(coordinates) >= max_rows:
                raise RuntimeError("Row limit reached; no data was modified")
            coordinates[oid] = safe_xy(shape, sr)
    fields = _double_field_map(source)
    missing = [n for n in (x_name, y_name) if n.lower() not in fields]
    if missing and not command.get("create_fields", False):
        raise ValueError("Missing numeric fields: " + ", ".join(missing))
    for n in (x_name, y_name):
        if n.lower() in fields and fields[n.lower()].type != "Double":
            raise ValueError("Field must be Double: " + n)
        if len(n) > 10 and source.lower().endswith(".shp"):
            raise ValueError("Shapefile field names cannot exceed 10 chars")
        if arcpy.ValidateFieldName(n, os.path.dirname(source)).lower() != n.lower():
            raise ValueError("Invalid output field name: " + n)
    for n in missing:
        arcpy.AddField_management(source, n, "DOUBLE")
    updated, empty = 0, 0
    with arcpy.da.UpdateCursor(layer, [x_name, y_name, "OID@"]) as cursor:
        for row in cursor:
            coord = coordinates[row[2]]
            if coord is None:
                empty += 1
                continue
            cursor.updateRow((coord[0], coord[1], row[2]))
            updated += 1
    arcpy.RefreshTOC()
    return {"ok": True, "layer_name": layer.name, "data_frame": df.name,
            "output_wkid": wkid, "updated": updated, "null_geometry": empty,
            "fields_created": missing, "non_atomic_dataset_write": True,
            "saved_mxd": False, "verified_on_arcmap": False}

# -*- coding: utf-8 -*-
"""ARC-10: CSV/Excel/DBF/EXIF GPS to a NEW point shapefile.

Photographs require embedded EXIF GPS; screenshot OCR is intentionally not
performed. New output only, no overwrite and no current MXD save.
"""
from __future__ import division
import csv
import io
import sys
import math
import os
import re
import uuid
import arcpy
from core.registry import action
from core.path_guard import guard_manual_write
from core.current_map import get_mxd, get_dataframe
from core.safety import require_live_write, require_geoprocessing, require_destructive

_DMS = re.compile(r"[-+]?\d+(?:[.,]\d+)?")
_EXTENSIONS = (".csv", ".xls", ".xlsx", ".dbf", ".jpg", ".jpeg", ".tif", ".tiff")


def parse_coordinate(value, axis):
    raw = str(value if value is not None else "").strip().upper()
    if not raw:
        raise ValueError("Missing " + axis + " coordinate")
    directional = [c for c in "NSEW" if c in raw]
    if directional and len(directional) != 1:
        raise ValueError("Invalid hemisphere")
    parts = [float(v.replace(",", ".")) for v in _DMS.findall(raw)]
    if len(parts) not in (1, 2, 3):
        raise ValueError("Expected decimal or DMS coordinate")
    sign = -1 if raw.startswith("-") or (directional and directional[0] in "SW") else 1
    absolute = abs(parts[0])
    if len(parts) > 1:
        if not 0 <= parts[1] < 60:
            raise ValueError("Invalid coordinate minutes")
        absolute += parts[1] / 60.0
    if len(parts) > 2:
        if not 0 <= parts[2] < 60:
            raise ValueError("Invalid coordinate seconds")
        absolute += parts[2] / 3600.0
    result = sign * absolute
    if math.isnan(result) or math.isinf(result):
        raise ValueError("Invalid numeric coordinate")
    if axis in ("x", "y") and directional:
        allowed = "EW" if axis == "x" else "NS"
        if directional[0] not in allowed:
            raise ValueError("Hemisphere does not match axis")
    return result


def _rational(value):
    if isinstance(value, tuple) and len(value) == 2:
        return float(value[0]) / float(value[1])
    return float(value)


def _photo_point(path):
    try:
        from PIL import Image
    except ImportError:
        raise RuntimeError("EXIF GPS import requires Pillow in ArcMap Python")
    image = Image.open(path)
    try:
        exif = image._getexif() if hasattr(image, "_getexif") else image.getexif()
        gps = exif.get(34853) if exif else None
        if not gps:
            raise ValueError("Photo has no embedded EXIF GPS; OCR not supported")
        def deg(values, ref):
            value = (_rational(values[0]) + _rational(values[1]) / 60.0 +
                     _rational(values[2]) / 3600.0)
            return -value if ref.upper() in ("S", "W") else value
        return [(deg(gps[4], gps[3]), deg(gps[2], gps[1]), "GPS-1")]
    finally:
        image.close()


def _csv_points(path, x_field, y_field, label_field, delimiter, max_rows):
    result = []
    # Python 2 csv expects bytes; Python 3 csv expects decoded text.
    stream = (io.open(path, "r", encoding="utf-8-sig", newline="")
              if sys.version_info[0] >= 3 else open(path, "rb"))
    with stream:
        reader = csv.DictReader(stream, delimiter=delimiter)
        if not reader.fieldnames:
            raise ValueError("CSV must contain a header")
        names = dict((k.strip().lstrip("\xef\xbb\xbf").lower(), k)
                     for k in reader.fieldnames)
        for required in (x_field.lower(), y_field.lower()):
            if required not in names:
                raise ValueError("Missing coordinate field: " + required)
        for idx, row in enumerate(reader):
            if idx >= max_rows:
                raise ValueError("Input exceeds max_rows")
            label_key = names.get(label_field.lower())
            label = row.get(label_key) if label_key else ""
            result.append((parse_coordinate(row[names[x_field.lower()]], "x"),
                           parse_coordinate(row[names[y_field.lower()]], "y"),
                           label or "PT-%d" % (idx + 1)))
    return result


def _table_points(table, x_field, y_field, label_field, max_rows):
    fields = dict((f.name.lower(), f.name) for f in arcpy.ListFields(table))
    if x_field.lower() not in fields or y_field.lower() not in fields:
        raise ValueError("X/Y columns not found in table")
    requested = [fields[x_field.lower()], fields[y_field.lower()]]
    label_name = fields.get(label_field.lower())
    if label_name:
        requested.append(label_name)
    result = []
    with arcpy.da.SearchCursor(table, requested) as cursor:
        for idx, row in enumerate(cursor):
            if idx >= max_rows:
                raise ValueError("Input exceeds max_rows")
            result.append((parse_coordinate(row[0], "x"),
                           parse_coordinate(row[1], "y"),
                           str(row[2]) if label_name and row[2] is not None
                           else "PT-%d" % (idx + 1)))
    return result


@action("import_coordinates_to_shp")
def import_coordinates_to_shp(command):
    for check in (require_live_write, require_geoprocessing, require_destructive):
        blocked = check()
        if blocked:
            return blocked
    if command.get("confirm_create_shp") is not True:
        return {"ok": False, "code": "CREATE_SHP_CONFIRMATION_REQUIRED"}
    source = os.path.abspath(str(command.get("input_path") or ""))
    output = os.path.abspath(str(command.get("output_shp") or ""))
    ext = os.path.splitext(source)[1].lower()
    if ext not in _EXTENSIONS or not os.path.isfile(source):
        raise ValueError("Input file must exist and be CSV, XLS/XLSX, DBF or GPS photo")
    if not output.lower().endswith(".shp") or os.path.exists(output):
        raise ValueError("Output must be a NEW .shp path (no overwrite)")
    folder, name = os.path.split(output)
    if not os.path.isdir(folder) or not name or len(name) > 100:
        raise ValueError("Output folder must already exist")
    blocked = guard_manual_write(output, "output_shp")
    if blocked:
        return blocked
    limit = int(command.get("max_rows", 10000))
    if not 1 <= limit <= 100000:
        raise ValueError("max_rows must be between 1 and 100000")
    x_field, y_field = str(command.get("x_field") or "X"), str(command.get("y_field") or "Y")
    label_field = str(command.get("label_field") or "LABEL")
    wkid = int(command.get("input_wkid", 4326))
    if ext in (".jpg", ".jpeg", ".tif", ".tiff"):
        if wkid != 4326:
            raise ValueError("Photo GPS EXIF coordinates are always WGS84")
        rows = _photo_point(source)
    elif ext == ".csv":
        sep = str(command.get("delimiter") or ",")
        if len(sep) != 1:
            raise ValueError("delimiter must be one character")
        rows = _csv_points(source, x_field, y_field, label_field, sep, limit)
    else:
        table = source
        temporary = None
        if ext in (".xls", ".xlsx"):
            temporary = "in_memory\\zagent_xy_" + uuid.uuid4().hex[:12]
            arcpy.ExcelToTable_conversion(source, temporary,
                                          command.get("sheet_name") or "")
            table = temporary
        try:
            rows = _table_points(table, x_field, y_field, label_field, limit)
        finally:
            if temporary and arcpy.Exists(temporary):
                arcpy.Delete_management(temporary)
    if not rows:
        raise ValueError("Input contains no coordinate rows")
    if wkid == 4326 and any(abs(x) > 180 or abs(y) > 90 for x, y, _ in rows):
        raise ValueError("WGS84 longitude/latitude outside valid bounds")
    sr = arcpy.SpatialReference(wkid)
    if sr.name == "Unknown":
        raise ValueError("Unknown input CRS")
    arcpy.CreateFeatureclass_management(folder, name, "POINT",
                                        spatial_reference=sr)
    try:
        arcpy.AddField_management(output, "LABEL", "TEXT", field_length=100)
        with arcpy.da.InsertCursor(output, ["SHAPE@XY", "LABEL"]) as cursor:
            for x, y, label in rows:
                cursor.insertRow(((x, y), str(label)[:100]))
    except Exception:
        arcpy.Delete_management(output)
        raise
    added_to_map, map_warning = False, None
    if command.get("add_to_map", False):
        try:
            mxd = get_mxd()
            df = get_dataframe(mxd, command.get("data_frame") or "")
            arcpy.mapping.AddLayer(df, arcpy.mapping.Layer(output), "TOP")
            arcpy.RefreshTOC()
            added_to_map = True
        except Exception as exc:
            # The SHP was already committed; never disguise that as a failed import.
            map_warning = str(exc)
    return {"ok": True, "output_shp": output, "points_created": len(rows),
            "input_wkid": wkid, "added_to_map": added_to_map,
            "map_warning": map_warning, "saved_mxd": False,
            "verified_on_arcmap": False}

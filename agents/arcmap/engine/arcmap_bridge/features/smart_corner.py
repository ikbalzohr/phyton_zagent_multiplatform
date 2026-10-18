# -*- coding: utf-8 -*-
"""Smart Corner Digitizer for CURRENT MXD, ArcMap 10.6.1 / ArcPy Python 2.7.

Preview/review are read-only; no MXD save. Dataset commit is deliberately
fail-closed, requires an explicit confirmation, guarded safe mode permissions,
unchanged source/target fingerprints, full shapefile backup and transaction journal.
"""
from __future__ import division, print_function

import glob
import hashlib
import json
import os
import shutil
import time
import uuid

import arcpy
from core.config import DATA_ROOT
from core.registry import action
from core.current_map import get_mxd, find_layer, safe_layer_source
from core.safety import require_live_write, require_destructive
from core.smart_corner_geometry import (classify_vertices, select_reviewed_candidates,
                                         canonical_hash, CornerGeometryError)

_PREVIEWS = {}
_PREVIEW_TTL_SECONDS = 1800
_MAX_PREVIEWS = 24
_JOURNAL_ROOT = os.path.join(DATA_ROOT, "smart_corner", "operations")
_BACKUP_ROOT = os.path.join(DATA_ROOT, "smart_corner", "backups")


class SmartCornerError(RuntimeError):
    def __init__(self, code, message):
        RuntimeError.__init__(self, code + ": " + message)
        self.code = code


def _check(condition, code, description):
    if not condition:
        raise SmartCornerError(code, description)


def _identity(command):
    # Correlation is injected by the Zagent MCP->IPC dispatcher, not supplied
    # from the tool's public arguments. Never share previews across chats.
    context = command.get("correlation") or {}
    session = str(context.get("session_id") or "")
    device = str(context.get("device_id") or "")
    operator = str(context.get("operator_alias") or "")
    _check(session and device and operator, "SESSION_IDENTITY_REQUIRED",
           "Authoritative session, device and operator correlation required")
    return {"session_id": session, "device_id": device, "operator_alias": operator}


def _require_preview_owner(preview, command):
    identity = _identity(command)
    _check(preview.get("identity") == identity, "SESSION_IDENTITY_MISMATCH",
           "Preview belongs to a different chat/device/operator")
    return identity


def _single_layer(name, dataframe):
    _check(bool(name), "SOURCE_MISSING", "Explicit layer name required")
    matches = find_layer(get_mxd(), str(name), dataframe or "")
    _check(len(matches) == 1, "LAYER_NOT_UNIQUE",
           "Expected exactly one CURRENT MXD layer named " + str(name))
    return matches[0]


def _shapefile_path(lyr, kind):
    path = safe_layer_source(lyr)
    _check(path and os.path.splitext(path)[1].lower() == ".shp" and os.path.isfile(path),
           "UNSUPPORTED_DATASET", kind + " must be an existing local .shp")
    return os.path.abspath(path)


def _digest_file(path):
    result = hashlib.sha256()
    with open(path, "rb") as stream:
        while True:
            block = stream.read(1048576)
            if not block:
                break
            result.update(block)
    return result.hexdigest()


def _sidecar_files(path):
    base, _ = os.path.splitext(path)
    folder = os.path.dirname(path)
    prefix = os.path.basename(base).lower() + "."
    found = []
    for name in os.listdir(folder):
        if not name.lower().startswith(prefix):
            continue
        low = name.lower()
        if low.endswith((".lock", ".lck", ".sr.lock", ".tmp")):
            continue
        candidate = os.path.join(folder, name)
        if os.path.isfile(candidate):
            found.append(candidate)
    return sorted(found)


def _signature(path):
    # Hash the authoritative geometry/schema sidecars. Auxiliary ArcGIS indices
    # can regenerate on read and are intentionally not part of optimistic lock.
    base, _ = os.path.splitext(path)
    content = {}
    for ext in (".shp", ".shx", ".dbf", ".prj", ".cpg"):
        file_path = base + ext
        if os.path.isfile(file_path):
            content[ext] = _digest_file(file_path)
    _check(all(k in content for k in (".shp", ".shx", ".dbf")),
           "INVALID_DATASET", "Shapefile core sidecars not found")
    return canonical_hash(content)


def _count(path):
    return int(arcpy.GetCount_management(path).getOutput(0))


def _context(command, require_target=True):
    mxd = get_mxd()
    source = command.get("source_layer") or ""
    source_df, source_lyr = _single_layer(source, command.get("data_frame"))
    df_name = source_df.name
    source_path = _shapefile_path(source_lyr, "source")
    target_lyr = None
    target_path = ""
    if require_target:
        target_name = command.get("target_layer") or ""
        target_df, target_lyr = _single_layer(target_name, df_name)
        _check(target_df.name == df_name, "DATAFRAME_MISMATCH", "Different data frames")
        target_path = _shapefile_path(target_lyr, "target")
        _check(os.path.normcase(target_path) != os.path.normcase(source_path),
               "INVALID_TARGET", "Target must not be the source")
        _check(str(arcpy.Describe(target_path).shapeType).lower() == "point",
               "INVALID_TARGET", "Target must be a Point shapefile")
    _check(str(arcpy.Describe(source_path).shapeType).lower() == "polygon",
           "INVALID_GEOMETRY", "Source must be a Polygon shapefile")
    return {"mxd": mxd, "mxd_path": str(getattr(mxd, "filePath", "") or ""),
            "data_frame": df_name, "source_layer": source_lyr,
            "target_layer": target_lyr, "source_path": source_path,
            "target_path": target_path,
            "source_fingerprint": _signature(source_path),
            "target_fingerprint": _signature(target_path) if target_path else "",
            "target_count": _count(target_path) if target_path else None}


def _geometry(command, context):
    feature_oid = command.get("feature_oid")
    shape = None
    selected_oid = None
    rows = 0
    # Data-source cursor avoids hidden CURRENT-layer selections changing results.
    with arcpy.da.SearchCursor(context["source_path"], ["OID@", "SHAPE@"]) as cursor:
        for oid, geom in cursor:
            if feature_oid is not None and int(oid) != int(feature_oid):
                continue
            rows += 1
            if rows > 1:
                break
            shape, selected_oid = geom, int(oid)
    _check(rows == 1 and shape is not None, "FEATURE_SELECTION_REQUIRED",
           "Source must contain exactly one polygon, or supply feature_oid")
    _check(not bool(getattr(shape, "isMultipart", False)) or int(shape.partCount) == 1,
           "MULTIPART_REVIEW_REQUIRED", "Multipart polygons are not supported in v1")
    _check(int(shape.partCount) == 1, "MULTIPART_REVIEW_REQUIRED",
           "Only a single outer ring is supported in v1")
    vertices = []
    part = shape.getPart(0)
    for idx, item in enumerate(part):
        if item is None:
            raise SmartCornerError("HOLE_REVIEW_REQUIRED", "Inner rings/holes unsupported")
        vertices.append({"x": float(item.X), "y": float(item.Y),
                         "vertex_index": idx})
    _check(len(vertices) >= 4, "INVALID_GEOMETRY", "Polygon ring requires closure")
    spatial_ref = shape.spatialReference
    kind = str(getattr(spatial_ref, "type", "") or "")
    unit = str(getattr(spatial_ref, "linearUnitName", "") or "")
    code = int(getattr(spatial_ref, "factoryCode", 0) or 0)
    _check(kind != "Unknown" and spatial_ref is not None, "INVALID_CRS",
           "Known polygon coordinate system required")
    if kind.lower() == "projected":
        metres = float(getattr(spatial_ref, "metersPerUnit", 0) or 0)
        _check(metres > 0, "INVALID_CRS", "Projected source needs positive metresPerUnit")
        for vertex in vertices:
            vertex["metric_x"] = vertex["x"] * metres
            vertex["metric_y"] = vertex["y"] * metres
        metric_crs = "projected_linear_" + unit
    elif kind.lower() == "geographic" and code == 4326:
        # WGS84 only: no implicit datum transformation. Use metric UTM for
        # analysis, but retain original WGS84 coordinates for future output.
        longs = [p["x"] for p in vertices[:-1]]
        lats = [p["y"] for p in vertices[:-1]]
        lon = sum(longs) / len(longs)
        lat = sum(lats) / len(lats)
        _check(-80 <= lat <= 84 and -180 <= lon <= 180, "INVALID_CRS",
               "WGS84 centroid outside supported UTM range")
        zone = max(1, min(60, int((lon + 180) // 6 + 1)))
        utm_code = (32600 if lat >= 0 else 32700) + zone
        utm = arcpy.SpatialReference(utm_code)
        for vertex in vertices:
            pt = arcpy.Point(vertex["x"], vertex["y"])
            projected = arcpy.PointGeometry(pt, spatial_ref).projectAs(utm).firstPoint
            vertex["metric_x"], vertex["metric_y"] = float(projected.X), float(projected.Y)
        metric_crs = "EPSG:" + str(utm_code)
    else:
        raise SmartCornerError("INVALID_CRS",
                               "Geographic datum must be WGS84 EPSG:4326 or projected CRS")
    return {"feature_oid": selected_oid, "vertices": vertices,
            "source_sr_wkid": code, "metric_crs": metric_crs,
            "coordinate_system": str(getattr(spatial_ref, "name", "") or "")}


def _prune_previews():
    cutoff = time.time() - _PREVIEW_TTL_SECONDS
    for key in list(_PREVIEWS.keys()):
        if _PREVIEWS[key]["created_at"] < cutoff:
            del _PREVIEWS[key]
    while len(_PREVIEWS) >= _MAX_PREVIEWS:
        oldest = min(_PREVIEWS, key=lambda k: _PREVIEWS[k]["created_at"])
        del _PREVIEWS[oldest]


def _latest(preview_id):
    _prune_previews()
    preview = _PREVIEWS.get(str(preview_id or ""))
    _check(preview is not None, "STALE_PREVIEW",
           "Preview missing/expired, or bridge restarted. Generate a new preview.")
    return preview


def _params(command):
    return {
        "min_turn_deg": float(command.get("min_turn_deg", 45.0)),
        "straight_turn_deg": float(command.get("straight_turn_deg", 3.0)),
        "collinear_tolerance_m": float(command.get("collinear_tolerance_m", 0.05)),
        "coordinate_epsilon_m": float(command.get("coordinate_epsilon_m", 1e-8)),
        "min_segment_length_m": float(command.get("min_segment_length_m", 0.0)),
    }


def _public_preview(preview, show_all=False):
    analysis = preview["analysis"]
    points = analysis["candidates"] if show_all else [
        c for c in analysis["candidates"] if c["class"] != "STRAIGHT"]
    selected = preview["reviewed"]
    return {
        "ok": True, "preview_id": preview["preview_id"],
        "review_revision": preview["revision"],
        "source_layer": preview["source_layer"], "target_layer": preview["target_layer"],
        "data_frame": preview["data_frame"], "feature_oid": preview["feature_oid"],
        "coordinate_system": preview["coordinate_system"], "metric_crs": preview["metric_crs"],
        "source_fingerprint": preview["source_fingerprint"],
        "target_fingerprint": preview["target_fingerprint"],
        "target_count": preview["target_count"],
        "parameters": preview["parameters"], "counts": analysis["counts"],
        "candidates": points, "reviewed_points": selected,
        "recommended_count": len(selected), "clockwise": True,
        "dry_run": True, "saved": False,
        "note": "REVIEW candidates excluded by default; preview has not written any SHP or MXD."
    }


@action("smart_corner_preflight")
def smart_corner_preflight(command):
    ctx = _context(command)
    geom = _geometry(command, ctx)
    fields = arcpy.ListFields(ctx["target_path"])
    id_name = command.get("id_field") or "Id"
    id_fields = [f for f in fields if f.name.lower() == id_name.lower()]
    _check(len(id_fields) == 1 and id_fields[0].type in ("Integer", "SmallInteger"),
           "TARGET_SCHEMA_UNSUPPORTED", "Numeric Id field required in existing target")
    return {"ok": True, "source_path": ctx["source_path"], "target_path": ctx["target_path"],
            "feature_oid": geom["feature_oid"], "vertex_count": len(geom["vertices"]) - 1,
            "target_count": ctx["target_count"],
            "source_fingerprint": ctx["source_fingerprint"],
            "target_fingerprint": ctx["target_fingerprint"], "target_id_field": id_fields[0].name,
            "metric_crs": geom["metric_crs"], "saved": False, "dry_run": True}


@action("smart_corner_preview")
def smart_corner_preview(command):
    ctx = _context(command)
    geom = _geometry(command, ctx)
    params = _params(command)
    result = classify_vertices(geom["vertices"], **params)
    reviewed = select_reviewed_candidates(result)
    _prune_previews()
    pid = uuid.uuid4().hex
    immutable = {
        "preview_id": pid, "identity": _identity(command),
        "mxd_path": ctx["mxd_path"],
        "source_path": ctx["source_path"], "target_path": ctx["target_path"],
        "source_layer": command["source_layer"], "target_layer": command["target_layer"],
        "data_frame": ctx["data_frame"], "feature_oid": geom["feature_oid"],
        "source_sr_wkid": geom["source_sr_wkid"],
        "coordinate_system": geom["coordinate_system"], "metric_crs": geom["metric_crs"],
        "source_fingerprint": ctx["source_fingerprint"],
        "target_fingerprint": ctx["target_fingerprint"],
        "target_count": ctx["target_count"], "analysis": result,
        "parameters": params, "created_at": time.time()
    }
    immutable["reviewed"] = reviewed
    immutable["revision"] = canonical_hash({
        "preview_id": pid, "selected": [x["vertex_index"] for x in reviewed],
        "source": ctx["source_fingerprint"], "target": ctx["target_fingerprint"]})
    _PREVIEWS[pid] = immutable
    return _public_preview(immutable, bool(command.get("include_straight", False)))


@action("smart_corner_review")
def smart_corner_review(command):
    preview = _latest(command.get("preview_id"))
    _require_preview_owner(preview, command)
    previous = str(command.get("expected_revision") or "")
    _check(previous == preview["revision"], "STALE_PREVIEW",
           "Review revision must match current preview revision")
    include = command.get("include_vertex_indices") or []
    exclude = command.get("exclude_vertex_indices") or []
    new_points = select_reviewed_candidates(preview["analysis"], include, exclude)
    preview["reviewed"] = new_points
    preview["revision"] = canonical_hash({
        "preview_id": preview["preview_id"], "selected": [x["vertex_index"] for x in new_points],
        "source": preview["source_fingerprint"], "target": preview["target_fingerprint"]})
    preview["reviewed_explicitly"] = True
    return _public_preview(preview)


def _journal_dir():
    if not os.path.isdir(_JOURNAL_ROOT):
        os.makedirs(_JOURNAL_ROOT)


def _journal_write(commit_id, stage, payload):
    _journal_dir()
    # Immutable stage files prevent silent replay on an uncertain write.
    path = os.path.join(_JOURNAL_ROOT, commit_id + "." + stage + ".json")
    data = json.dumps(payload, sort_keys=True, ensure_ascii=True, indent=2)
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(data.encode("utf-8"))
        stream.flush()
        os.fsync(stream.fileno())


def _journal_stage(commit_id):
    matches = glob.glob(os.path.join(_JOURNAL_ROOT, commit_id + ".*.json"))
    if not matches:
        return None
    name = os.path.basename(sorted(matches)[-1])
    stage = name[len(commit_id) + 1:-5]
    with open(sorted(matches)[-1], "rb") as stream:
        return {"stage": stage, "entry": json.loads(stream.read().decode("utf-8"))}


def _shp_backup(path, commit_id):
    folder = os.path.join(_BACKUP_ROOT, commit_id)
    _check(not os.path.exists(folder), "COMMIT_CONFLICT", "Backup already exists")
    os.makedirs(folder)
    files = _sidecar_files(path)
    _check(all(any(x.lower().endswith(ext) for x in files)
               for ext in (".shp", ".shx", ".dbf")),
           "INVALID_TARGET", "Shapefile core sidecars are missing")
    result = {}
    for source in files:
        dest = os.path.join(folder, os.path.basename(source))
        shutil.copy2(source, dest)
        _check(_digest_file(source) == _digest_file(dest),
               "BACKUP_VERIFICATION_FAILED", "Copied backup mismatch")
        result[os.path.basename(source)] = _digest_file(dest)
    return {"root": folder, "files": result}


def _target_schema(path, id_field, label_field):
    fields = arcpy.ListFields(path)
    ids = [x for x in fields if x.name.lower() == id_field.lower()]
    _check(len(ids) == 1 and ids[0].type in ("Integer", "SmallInteger"),
           "TARGET_SCHEMA_UNSUPPORTED", "Target requires numeric Id field")
    labels = [x for x in fields if x.name.lower() == label_field.lower()] if label_field else []
    if label_field:
        _check(len(labels) == 1 and labels[0].type == "String",
               "TARGET_SCHEMA_UNSUPPORTED", "Optional label field must be a String")
    extras = [x for x in fields if x.type not in ("OID", "Geometry") and
              x.name.lower() not in (ids[0].name.lower(),
                                     labels[0].name.lower() if labels else "")]
    # Deleting all target features is always destructive; don't synthesize
    # required per-feature values for unrelated attributes.
    _check(not any(x.required and not x.isNullable for x in extras),
           "TARGET_SCHEMA_UNSUPPORTED", "Other mandatory target fields would be lost")
    return ids[0].name, labels[0].name if labels else ""


def _reconcile_preview(preview):
    command = {"source_layer": preview["source_layer"],
               "target_layer": preview["target_layer"],
               "data_frame": preview["data_frame"]}
    current = _context(command)
    _check(current["mxd_path"] == preview["mxd_path"],
           "CURRENT_MXD_CHANGED", "Current document changed since preview")
    _check(os.path.normcase(current["source_path"]) == os.path.normcase(preview["source_path"]) and
           os.path.normcase(current["target_path"]) == os.path.normcase(preview["target_path"]),
           "TARGET_STALE", "Layer source paths changed since preview")
    _check(current["source_fingerprint"] == preview["source_fingerprint"] and
           current["target_fingerprint"] == preview["target_fingerprint"] and
           current["target_count"] == preview["target_count"],
           "STALE_PREVIEW", "Source or target SHP content changed since preview")
    geometry = _geometry({"feature_oid": preview["feature_oid"]}, current)
    analysis = classify_vertices(geometry["vertices"], **preview["parameters"])
    expected = [(x["vertex_index"], x["x"], x["y"])
                for x in preview["analysis"]["candidates"]]
    observed = [(x["vertex_index"], x["x"], x["y"]) for x in analysis["candidates"]]
    _check(observed == expected, "STALE_PREVIEW", "Polygon vertices changed")
    return current


def _commit_edit(path, points, sr, id_field, label_field, label_prefix, mode):
    workspace = os.path.dirname(path)
    editor = arcpy.da.Editor(workspace)
    editing, in_operation = False, False
    try:
        editor.startEditing(False, False)
        editing = True
        editor.startOperation()
        in_operation = True
        if mode == "replace":
            with arcpy.da.UpdateCursor(path, ["OID@"]) as existing:
                for _ in existing:
                    existing.deleteRow()
        fields = ["SHAPE@", id_field] + ([label_field] if label_field else [])
        with arcpy.da.InsertCursor(path, fields) as sink:
            for item in points:
                geom = arcpy.PointGeometry(arcpy.Point(item["x"], item["y"]), sr)
                row = [geom, int(item["Id"])]
                if label_field:
                    row.append(label_prefix + str(item["Id"]))
                sink.insertRow(row)
        editor.stopOperation()
        in_operation = False
        editor.stopEditing(True)
        editing = False
    except Exception:
        if in_operation:
            try:
                editor.abortOperation()
            except Exception:
                pass
        if editing:
            try:
                editor.stopEditing(False)
            except Exception:
                pass
        raise


@action("smart_corner_commit")
def smart_corner_commit(command):
    if command.get("dry_run", True):
        return {"ok": False, "code": "DRY_RUN_ONLY",
                "error": "dry_run=false is required to mutate a SHP", "saved": False}
    blocked = require_live_write() or require_destructive()
    if blocked:
        return blocked
    preview = _latest(command.get("preview_id"))
    _require_preview_owner(preview, command)
    _check(command.get("expected_revision") == preview["revision"],
           "STALE_PREVIEW", "Current review revision required")
    _check(command.get("confirm_commit") is True,
           "CONFIRMATION_REQUIRED", "confirm_commit=true required")
    _check(bool(preview.get("reviewed_explicitly")),
           "REVIEW_REQUIRED", "Run smart_corner_review before commit")
    mode = command.get("write_mode") or "replace"
    _check(mode == "replace", "UNSUPPORTED_WRITE_MODE", "Only reviewed replace is supported in v1")
    idempotency_key = str(command.get("idempotency_key") or "")
    _check(len(idempotency_key) >= 12, "IDEMPOTENCY_REQUIRED", "Unique idempotency_key required")
    current = _reconcile_preview(preview)
    nonempty = current["target_count"] > 0
    if nonempty:
        _check(command.get("confirm_replace_nonempty") is True,
               "NONEMPTY_TARGET_CONFIRMATION_REQUIRED",
               "Explicit confirmation to replace existing point records required")
        _check(command.get("expected_target_count") == current["target_count"],
               "TARGET_STALE", "Caller must acknowledge exact previous record count")
    _check(arcpy.TestSchemaLock(current["target_path"]),
           "TARGET_LOCKED", "Target SHP schema is locked; close editors and retry")
    source_sr = arcpy.Describe(current["source_path"]).spatialReference
    target_sr = arcpy.Describe(current["target_path"]).spatialReference
    _check(target_sr.exportToString() == source_sr.exportToString(),
           "INVALID_CRS", "Source and target spatial references differ")
    id_field = command.get("id_field") or "Id"
    label_field = command.get("label_field") or ""
    id_field, label_field = _target_schema(current["target_path"], id_field, label_field)
    points = preview["reviewed"]
    _check(len(points) >= 3, "ZERO_CANDIDATES", "No reviewed corners to write")
    commit_id = canonical_hash({"revision": preview["revision"],
                                "key": idempotency_key})[:32]
    previous = _journal_stage(commit_id)
    if previous:
        return {"ok": False, "code": "COMMIT_REPLAY_REQUIRES_RECONCILIATION",
                "commit_id": commit_id, "last_stage": previous["stage"],
                "error": "Existing journal found. Inspect status; never blindly replay.", "saved": False}
    details = {"commit_id": commit_id, "preview_id": preview["preview_id"],
               "identity": preview["identity"],
               "revision": preview["revision"], "target_path": current["target_path"],
               "source_path": current["source_path"], "source_fingerprint": current["source_fingerprint"],
               "target_fingerprint_before": current["target_fingerprint"],
               "target_count_before": current["target_count"], "point_count": len(points),
               "id_field": id_field, "label_field": label_field,
               "timestamp": time.time()}
    _journal_write(commit_id, "00_PREPARING", details)
    backup = _shp_backup(current["target_path"], commit_id)
    details["backup"] = backup
    _journal_write(commit_id, "10_BACKED_UP", details)
    _check(_signature(current["target_path"]) == current["target_fingerprint"],
           "TARGET_STALE", "Target changed during backup")
    _journal_write(commit_id, "20_COMMITTING", details)
    try:
        # ArcPy geometries are constructed using original source coordinates.
        _commit_edit(current["target_path"], points, target_sr, id_field, label_field,
                     str(command.get("label_prefix", "Pt")), mode)
    except Exception as exc:
        details["write_error"] = str(exc)
        _journal_write(commit_id, "30_WRITE_UNCERTAIN", details)
        return {"ok": False, "code": "UNKNOWN_COMMIT_OUTCOME", "commit_id": commit_id,
                "error": str(exc), "backup": backup["root"], "saved": False,
                "manual_reconciliation_required": True}
    try:
        after = _count(current["target_path"])
        _check(after == len(points), "POST_COMMIT_QA_FAILED", "Target record count mismatch")
        actual = []
        with arcpy.da.SearchCursor(current["target_path"], [id_field, "SHAPE@XY"]) as rows:
            for item_id, xy in rows:
                actual.append((int(item_id), float(xy[0]), float(xy[1])))
        actual.sort()
        expected = sorted((int(p["Id"]), p["x"], p["y"]) for p in points)
        tol = float(command.get("coordinate_verification_tolerance", 1e-8))
        _check(len(actual) == len(expected) and all(
            a[0] == e[0] and abs(a[1] - e[1]) <= tol and abs(a[2] - e[2]) <= tol
            for a, e in zip(actual, expected)), "POST_COMMIT_QA_FAILED",
            "Target Id / original vertex coordinates mismatch")
        details["target_fingerprint_after"] = _signature(current["target_path"])
        details["target_count_after"] = after
        _journal_write(commit_id, "40_COMMITTED", details)
        return {"ok": True, "commit_id": commit_id, "count": after,
                "target_path": current["target_path"],
                "backup": backup["root"], "saved": False,
                "target_fingerprint_after": details["target_fingerprint_after"]}
    except Exception as exc:
        details["qa_error"] = str(exc)
        _journal_write(commit_id, "35_QA_UNCERTAIN", details)
        return {"ok": False, "code": "POST_COMMIT_QA_FAILED", "commit_id": commit_id,
                "error": str(exc), "saved": False,
                "manual_reconciliation_required": True, "backup": backup["root"]}


@action("smart_corner_status")
def smart_corner_status(command):
    commit_id = str(command.get("commit_id") or "")
    _check(len(commit_id) == 32 and all(ch in "0123456789abcdef" for ch in commit_id),
           "INVALID_COMMIT_ID", "32-digit hexadecimal commit_id required")
    value = _journal_stage(commit_id)
    _check(value is not None, "UNKNOWN_COMMIT", "No durable commit journal entry")
    _check(value["entry"].get("identity") == _identity(command),
           "SESSION_IDENTITY_MISMATCH", "Commit belongs to another session")
    return {"ok": True, "commit_id": commit_id, "stage": value["stage"],
            "details": value["entry"], "saved": False}


@action("smart_corner_validate")
def smart_corner_validate(command):
    if command.get("commit_id"):
        result = smart_corner_status(command)
        entry = result["details"]
        path = entry["target_path"]
        if not os.path.isfile(path):
            return {"ok": False, "code": "TARGET_MISSING", "commit_id": command["commit_id"]}
        result["current_target_fingerprint"] = _signature(path)
        result["current_target_count"] = _count(path)
        result["matches_committed_target"] = (
            result["stage"] == "40_COMMITTED" and
            result["current_target_fingerprint"] == entry.get("target_fingerprint_after"))
        return result
    preview = _latest(command.get("preview_id"))
    _require_preview_owner(preview, command)
    _reconcile_preview(preview)
    return _public_preview(preview, bool(command.get("include_straight", False)))


@action("smart_corner_rollback")
def smart_corner_rollback(command):
    blocked = require_live_write() or require_destructive()
    if blocked:
        return blocked
    _check(command.get("confirm_rollback") is True,
           "CONFIRMATION_REQUIRED", "confirm_rollback=true required")
    result = smart_corner_status(command)
    state = result["stage"]
    entry = result["details"]
    _check(state == "40_COMMITTED", "RECONCILIATION_REQUIRED",
           "Only confirmed complete commits support automatic rollback")
    path = entry["target_path"]
    _check(os.path.isfile(path), "TARGET_MISSING", "Target SHP not found")
    _check(_signature(path) == entry["target_fingerprint_after"],
           "TARGET_STALE", "Target changed since commit; do not overwrite")
    _check(arcpy.TestSchemaLock(path), "TARGET_LOCKED",
           "Target is locked; request manual restore after releasing locks")
    backup = entry.get("backup", {})
    backup_root = backup.get("root")
    files = backup.get("files") or {}
    _check(backup_root and files, "BACKUP_MISSING", "No verified backup manifest")
    for name, digest in files.items():
        _check(name == os.path.basename(name) and _digest_file(
            os.path.join(backup_root, name)) == digest,
            "BACKUP_VERIFICATION_FAILED", "Backup file hash changed")
    commit_id = result["commit_id"]
    _journal_write(commit_id, "50_ROLLBACK_STARTED", entry)
    try:
        for name in sorted(files):
            shutil.copy2(os.path.join(backup_root, name),
                         os.path.join(os.path.dirname(path), name))
        _check(_signature(path) == entry["target_fingerprint_before"],
               "ROLLBACK_FAILED", "Restored SHP hash does not match original")
        _journal_write(commit_id, "60_ROLLED_BACK", entry)
    except Exception as exc:
        _journal_write(commit_id, "55_ROLLBACK_UNCERTAIN",
                       {"error": str(exc), "backup": backup,
                        "target_path": path, "identity": entry["identity"]})
        return {"ok": False, "code": "ROLLBACK_FAILED", "error": str(exc),
                "manual_recovery_required": True, "commit_id": commit_id, "saved": False}
    return {"ok": True, "commit_id": commit_id, "rolled_back": True,
            "target_path": path, "saved": False}

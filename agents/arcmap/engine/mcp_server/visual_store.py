import datetime as _dt
import hashlib
import json
import os
import re
import shutil
import time
import uuid
from .request_context import current
from .execution_context import owner_key


def visual_base_root():
    configured = (os.environ.get("ZAGENT_VISUAL_ROOT") or "").strip()
    if configured:
        return os.path.abspath(configured)
    data_root = os.path.abspath(
        os.environ.get(
            "ZAGENT_ARCMAP_DATA_ROOT",
            os.path.join(os.path.dirname(__file__), os.pardir, "data"),
        )
    )
    return os.path.abspath(os.path.join(data_root, os.pardir, "visual"))


def visual_root():
    return os.path.join(visual_base_root(), "owners", owner_key(current())[len("owner_v1_"):])


def _dirs():
    root = visual_root()
    artifacts = os.path.join(root, "artifacts")
    manifests = os.path.join(root, "manifests")
    staging = os.path.join(root, "staging")
    for item in (root, artifacts, manifests, staging):
        if not os.path.isdir(item):
            os.makedirs(item, exist_ok=True)
    return root, artifacts, manifests, staging


def _safe(value):
    value = re.sub(r"[^a-zA-Z0-9._-]+", "_", str(value or "visual"))
    return value.strip("_") or "visual"


def staging_path(name="arcmap", extension=".png"):
    _, _, _, staging = _dirs()
    ext = extension if str(extension).startswith(".") else "." + str(extension)
    stamp = _dt.datetime.utcnow().strftime("%Y%m%dT%H%M%S%f")
    return os.path.join(staging, "%s_%s%s" % (_safe(name), stamp, ext))


def _sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _atomic_json(path, value):
    parent = os.path.dirname(path)
    if not os.path.isdir(parent):
        os.makedirs(parent, exist_ok=True)
    tmp = path + ".%s.tmp" % uuid.uuid4().hex
    with open(tmp, "w", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, sort_keys=False)
    os.replace(tmp, path)


def publish(path, source="arcmap", kind="layout-snapshot", label=None,
            session_id=None, request_id=None, trace_id=None, metadata=None):
    context = current()
    bound_session = context.get("session_id")
    if not bound_session:
        raise ValueError("SESSION_IDENTITY_REQUIRED: visual publish needs Tunnel session metadata.")
    if session_id and session_id != bound_session:
        raise ValueError("SESSION_IDENTITY_MISMATCH: visual session cannot be overridden.")
    session_id = bound_session
    request_id = context.get("request_id")
    trace_id = context.get("trace_id")
    root, artifacts, manifests, _ = _dirs()
    original = os.path.abspath(path)
    if not os.path.isfile(original):
        raise IOError("Visual artifact source does not exist: %s" % original)

    ext = os.path.splitext(original)[1].lower() or ".bin"
    artifact_id = "vis_%s_%s" % (
        int(time.time() * 1000),
        uuid.uuid4().hex[:12],
    )
    final_path = os.path.join(artifacts, artifact_id + ext)
    shutil.copy2(original, final_path)

    mime = {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".webp": "image/webp",
        ".gif": "image/gif",
        ".mp4": "video/mp4",
        ".webm": "video/webm",
    }.get(ext, "application/octet-stream")

    manifest = {
        "schemaVersion": 1,
        "id": artifact_id,
        "source": source,
        "kind": kind,
        "label": (str(label).strip() if label else None),
        "capturedAt": _dt.datetime.utcnow().replace(
            tzinfo=_dt.timezone.utc
        ).isoformat().replace("+00:00", "Z"),
        "artifactPath": final_path,
        "originalPath": original,
        "mimeType": mime,
        "bytes": os.path.getsize(final_path),
        "sha256": _sha256(final_path),
        "provenance": {
            "principalId": context.get("principal_id"),
            "workspaceId": context.get("workspace_id"),
            "jobId": context.get("job_id") or context.get("run_id"),
            "operationId": context.get("operation_id"),
            "deviceId": context.get("device_id") or (os.environ.get("ZAGENT_DEVICE_ID") or "").strip() or None,
            "deviceName": (os.environ.get("ZAGENT_DEVICE_NAME") or "").strip() or None,
            "sessionId": session_id or (os.environ.get("ZAGENT_SESSION_ID") or "").strip() or None,
            "requestId": request_id or (os.environ.get("ZAGENT_REQUEST_ID") or "").strip() or None,
            "traceId": trace_id or (os.environ.get("ZAGENT_TRACE_ID") or "").strip() or None,
        },
        "metadata": metadata or {},
    }

    _atomic_json(os.path.join(manifests, artifact_id + ".json"), manifest)
    _atomic_json(os.path.join(root, "latest.json"), manifest)
    # Bridge: also publish the flat public path (backward-compat) alongside the
    # per-owner manifest. Original per-owner data is never deleted.
    _atomic_json(os.path.join(visual_base_root(), "latest.json"), manifest)
    return manifest


def list_artifacts(source=None, limit=50, _all_sessions=False):
    _, artifacts, manifests, _ = _dirs()
    items = []
    for name in os.listdir(manifests):
        if not name.lower().endswith(".json"):
            continue
        try:
            with open(os.path.join(manifests, name), "r", encoding="utf-8") as stream:
                item = json.load(stream)
            # No cross-owner bypass: _all_sessions is retained only for local signature compatibility.
            provenance = item.get('provenance', {})
            ctx = current()
            if provenance.get('principalId') != ctx.get('principal_id') or provenance.get('workspaceId') != ctx.get('workspace_id'):
                continue
            actual = os.path.realpath(item.get('artifactPath') or '')
            if os.path.commonpath([actual, os.path.realpath(artifacts)]) != os.path.realpath(artifacts):
                continue
            if not os.path.isfile(actual) or os.path.getsize(actual) != item.get('bytes') or _sha256(actual) != item.get('sha256'):
                continue
            if source and item.get("source") != source:
                continue
            items.append(item)
        except Exception:
            continue
    items.sort(key=lambda item: item.get("capturedAt") or "", reverse=True)
    return items[:max(1, min(int(limit or 50), 5000))]


def latest(source=None):
    items = list_artifacts(source=source, limit=1)
    return items[0] if items else None


def prune(max_artifacts=200, max_age_hours=None):
    root, _, manifests, _ = _dirs()
    max_artifacts = max(1, min(int(max_artifacts or 200), 5000))
    max_age_seconds = (
        float(max_age_hours) * 3600.0
        if max_age_hours is not None and float(max_age_hours) > 0
        else None
    )
    now = _dt.datetime.now(tz=_dt.timezone.utc).timestamp()
    items = list_artifacts(limit=5000)
    remove = []
    for index, item in enumerate(items):
        captured = item.get("capturedAt")
        too_old = False
        if max_age_seconds and captured:
            try:
                timestamp = _dt.datetime.fromisoformat(
                    captured.replace("Z", "+00:00")
                ).timestamp()
                too_old = (now - timestamp) > max_age_seconds
            except Exception:
                pass
        if index >= max_artifacts or too_old:
            remove.append(item)

    for item in remove:
        try:
            os.remove(item.get("artifactPath") or "")
        except Exception:
            pass
        try:
            os.remove(os.path.join(manifests, str(item.get("id")) + ".json"))
        except Exception:
            pass

    remaining = list_artifacts(limit=1, _all_sessions=True)
    latest_path = os.path.join(root, "latest.json")
    flat_latest_path = os.path.join(visual_base_root(), "latest.json")
    if remaining:
        _atomic_json(latest_path, remaining[0])
        _atomic_json(flat_latest_path, remaining[0])
    else:
        try:
            os.remove(latest_path)
        except Exception:
            pass
        try:
            os.remove(flat_latest_path)
        except Exception:
            pass
    return {"removed": len(remove), "retained": max(0, len(items) - len(remove))}
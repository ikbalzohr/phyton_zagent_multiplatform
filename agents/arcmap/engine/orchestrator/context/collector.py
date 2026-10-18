import hashlib
import json
import time

_VOLATILE_KEYS = {
    "request_id", "trace_id", "task_id", "operation_id", "mcp_receive_epoch",
    "created_at", "updated_at", "started_at", "finished_at", "heartbeat_at",
    "duration_ms", "elapsed_ms", "timing", "timings", "timestamp", "timestamp_utc",
    "collected_at", "correlation", "fingerprint",
}

def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)

def _stable_value(value):
    if isinstance(value, dict):
        return {
            k: _stable_value(v)
            for k, v in value.items()
            if k not in _VOLATILE_KEYS and not k.endswith("_epoch")
        }
    if isinstance(value, list):
        return [_stable_value(v) for v in value]
    if isinstance(value, float):
        # ArcObjects may return semantically identical layout/extent doubles
        # with sub-nanounit representation noise after snapshot/restore.
        # Nine decimal places is far below meaningful ArcMap layout/GIS
        # mutation precision while keeping the context hash deterministic.
        return round(value, 9)
    return value

def _safe_call(services, action, timeout=10):
    try:
        result = services.call(action, timeout=timeout)
        if isinstance(result, dict):
            return result
        return {"ok": False, "error": "NON_OBJECT_RESULT", "value": result}
    except Exception as exc:
        return {"ok": False, "error": type(exc).__name__, "details": str(exc)}

def _fingerprint(results, revision):
    stable = _stable_value({
        "ping": results.get("ping"),
        "status": results.get("status"),
        "map": results.get("map"),
        "layers": results.get("layers"),
        "layout": results.get("layout"),
        "dataframe": results.get("dataframe"),
        "document_revision": revision,
    })
    return hashlib.sha256(_canonical(stable).encode("utf-8")).hexdigest()

def collect_live_context(services):
    """Collect one read-only ArcMap context DTO.

    Ping is a fail-fast gate. If the bridge is offline we do not enqueue four
    additional IPC requests that are guaranteed to time out.
    """
    collected_at = time.time()
    owner = None
    owner_probe = getattr(services, "bridge_owner_status", None)
    if callable(owner_probe):
        try:
            owner = owner_probe()
        except Exception:
            owner = None
    if isinstance(owner, dict) and not bool(owner.get("healthy")):
        ping = {
            "ok": False,
            "code": "BRIDGE_OFFLINE",
            "error": "BRIDGE_OFFLINE: no fresh UI-thread heartbeat; command not queued.",
            "owner": owner,
        }
        results = {"ping": ping, "status": None, "map": None, "layers": None, "layout": None, "dataframe": None}
        return {
            "schema_version": "2.0",
            "available": False,
            "collected_at": collected_at,
            "source": "arcmap-live-readonly",
            "errors": [{"source": "bridge_owner", "error": "BRIDGE_OFFLINE"}],
            **results,
            "document_revision": None,
            "fingerprint": _fingerprint(results, None),
        }

    ping = _safe_call(services, "ping", timeout=3)
    if not bool(ping.get("ok")):
        results = {"ping": ping, "status": None, "map": None, "layers": None, "layout": None, "dataframe": None}
        error = {"source": "ping", "error": ping.get("error") or ping.get("code") or "UNAVAILABLE"}
        return {
            "schema_version": "2.0",
            "available": False,
            "collected_at": collected_at,
            "source": "arcmap-live-readonly",
            "errors": [error],
            **results,
            "document_revision": None,
            "fingerprint": _fingerprint(results, None),
        }

    results = {
        "ping": ping,
        "status": _safe_call(services, "status", timeout=5),
        "map": _safe_call(services, "inspect_current_map", timeout=10),
        "layers": _safe_call(services, "list_layers", timeout=10),
        "layout": _safe_call(services, "list_layout_elements", timeout=10),
        "dataframe": _safe_call(services, "get_dataframe_state", timeout=10),
    }
    errors = []
    for name, result in results.items():
        if result is None or not bool(result.get("ok")):
            errors.append({"source": name, "error": (result or {}).get("error") or (result or {}).get("code") or "UNAVAILABLE"})
    revision = None
    for name in ("ping", "status", "map"):
        item = results[name]
        if isinstance(item, dict):
            revision = item.get("revision") or item.get("document_revision") or item.get("context") or revision
    return {
        "schema_version": "2.0",
        "available": not errors,
        "collected_at": collected_at,
        "source": "arcmap-live-readonly",
        "errors": errors,
        **results,
        "document_revision": revision,
        "fingerprint": _fingerprint(results, revision),
    }

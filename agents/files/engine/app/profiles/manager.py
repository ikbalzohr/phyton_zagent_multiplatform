from __future__ import annotations

import json
import os
import threading
import uuid
from contextvars import ContextVar

BOUND_PROFILE = ContextVar("zagent_profile", default=None)
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

from app.paths import CONFIG_DIR, DATA_ROOT, LOG_DIR
DATA_DIR = DATA_ROOT
PROFILES_FILE = CONFIG_DIR / "profiles.json"
PENDING_FILE = DATA_DIR / "pending_profile_requests.json"
AUDIT_FILE = LOG_DIR / "profile_audit.jsonl"

_LOCK = threading.RLock()


def _now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def _write_json_atomic(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8", newline="\n") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")
    os.replace(tmp, path)


def _audit(action: str, **payload: Any) -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    record = {"time": _now(), "action": action, **payload}
    with AUDIT_FILE.open("a", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def _normalize_root(root: str) -> str:
    if not root or not str(root).strip():
        raise ValueError("Path tidak boleh kosong.")
    p = os.path.abspath(os.path.expandvars(os.path.expanduser(str(root).strip())))
    if not os.path.isdir(p):
        raise ValueError(f"Folder tidak ditemukan: {p}")
    drive, tail = os.path.splitdrive(p)
    if tail in ("\\", "/"):
        raise ValueError("Root drive penuh tidak diizinkan sebagai profile.")
    return os.path.normpath(p)


def _validate_name(name: str) -> str:
    value = str(name or "").strip()
    if not value:
        raise ValueError("Nama profile tidak boleh kosong.")
    allowed = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_")
    if any(c not in allowed for c in value):
        raise ValueError("Nama profile hanya boleh berisi huruf, angka, '-' dan '_'.")
    return value


def load_profiles() -> Dict[str, Any]:
    with _LOCK:
        return _read_json(PROFILES_FILE, {"schema_version": "2.0", "active_profile": None, "profiles": []})


def save_profiles(data: Dict[str, Any]) -> None:
    with _LOCK:
        _write_json_atomic(PROFILES_FILE, data)


def list_profiles() -> List[Dict[str, Any]]:
    data = load_profiles()
    bound = BOUND_PROFILE.get()
    active = bound.get("name") if bound is not None else data.get("active_profile")
    out = []
    for p in data.get("profiles", []):
        item = dict(p)
        item["active"] = p.get("name") == active
        out.append(item)
    return out


def get_profile(name: str) -> Dict[str, Any]:
    for p in load_profiles().get("profiles", []):
        if p.get("name") == name:
            return dict(p)
    raise KeyError(f"Profile tidak ditemukan: {name}")


def load_requests() -> Dict[str, Any]:
    with _LOCK:
        return _read_json(PENDING_FILE, {"schema_version": "2.0", "requests": []})


def save_requests(data: Dict[str, Any]) -> None:
    with _LOCK:
        _write_json_atomic(PENDING_FILE, data)


def list_requests(status: str | None = None) -> List[Dict[str, Any]]:
    rows = load_requests().get("requests", [])
    if status:
        rows = [r for r in rows if r.get("status") == status]
    return rows


def _new_request(kind: str, payload: Dict[str, Any], requested_by: str = "chatgpt") -> Dict[str, Any]:
    with _LOCK:
        data = load_requests()
        request = {
            "request_id": "PRF-" + uuid.uuid4().hex[:12].upper(),
            "kind": kind,
            "status": "pending_user_approval",
            "requested_by": requested_by,
            "requested_at": _now(),
            "payload": payload,
        }
        data.setdefault("requests", []).append(request)
        save_requests(data)
        _audit("profile_request_created", request_id=request["request_id"], kind=kind, requested_by=requested_by, payload=payload)
        return request


def request_add(name: str, root: str, mode: str = "read-only", description: str = "", requested_by: str = "chatgpt") -> Dict[str, Any]:
    name = _validate_name(name)
    root = _normalize_root(root)
    mode = str(mode).strip().lower()
    if mode not in {"read-only", "read-write"}:
        raise ValueError("Mode harus read-only atau read-write.")
    existing = load_profiles().get("profiles", [])
    if any(p.get("name") == name for p in existing):
        raise ValueError(f"Nama profile sudah digunakan: {name}")
    if any(os.path.normcase(p.get("root", "")) == os.path.normcase(root) for p in existing):
        raise ValueError(f"Path sudah terdaftar pada profile lain: {root}")
    return _new_request("add", {"name": name, "root": root, "mode": mode, "description": description}, requested_by)


def request_update(name: str, *, root: str | None = None, mode: str | None = None, description: str | None = None, enabled: bool | None = None, requested_by: str = "chatgpt") -> Dict[str, Any]:
    current = get_profile(name)
    changes: Dict[str, Any] = {}
    if root is not None:
        changes["root"] = _normalize_root(root)
    if mode is not None:
        mode = str(mode).strip().lower()
        if mode not in {"read-only", "read-write"}:
            raise ValueError("Mode harus read-only atau read-write.")
        changes["mode"] = mode
    if description is not None:
        changes["description"] = str(description)
    if enabled is not None:
        changes["enabled"] = bool(enabled)
    if not changes:
        raise ValueError("Tidak ada perubahan yang diminta.")
    privilege_escalation = current.get("mode") == "read-only" and changes.get("mode") == "read-write"
    return _new_request("update", {"name": name, "changes": changes, "privilege_escalation": privilege_escalation}, requested_by)


def request_delete(name: str, requested_by: str = "chatgpt") -> Dict[str, Any]:
    get_profile(name)
    return _new_request("delete", {"name": name}, requested_by)


def get_request(request_id: str) -> Dict[str, Any]:
    for r in load_requests().get("requests", []):
        if r.get("request_id") == request_id:
            return dict(r)
    raise KeyError(f"Request tidak ditemukan: {request_id}")


def approve_request(request_id: str, authorized_by: str = "local_user") -> Dict[str, Any]:
    with _LOCK:
        reqs = load_requests()
        req = next((r for r in reqs.get("requests", []) if r.get("request_id") == request_id), None)
        if not req:
            raise KeyError(f"Request tidak ditemukan: {request_id}")
        if req.get("status") != "pending_user_approval":
            raise ValueError("Request ini tidak lagi pending.")

        profiles = load_profiles()
        rows = profiles.setdefault("profiles", [])
        kind = req.get("kind")
        payload = req.get("payload", {})

        if kind == "add":
            if any(p.get("name") == payload["name"] for p in rows):
                raise ValueError("Profile sudah ada.")
            new_profile = dict(payload)
            new_profile.update({
                "enabled": True,
                "authorized_by_user": True,
                "authorized_at": _now(),
                "authorization_source": "local_ui",
            })
            rows.append(new_profile)
        elif kind == "update":
            target = next((p for p in rows if p.get("name") == payload["name"]), None)
            if not target:
                raise KeyError("Profile target tidak ditemukan.")
            target.update(payload.get("changes", {}))
            target["authorized_by_user"] = True
            target["authorized_at"] = _now()
            target["authorization_source"] = "local_ui"
        elif kind == "delete":
            target_name = payload["name"]
            if profiles.get("active_profile") == target_name:
                raise ValueError("Profile aktif tidak boleh dihapus. Switch ke profile lain terlebih dahulu.")
            before = len(rows)
            rows[:] = [p for p in rows if p.get("name") != target_name]
            if len(rows) == before:
                raise KeyError("Profile target tidak ditemukan.")
        else:
            raise ValueError(f"Jenis request tidak dikenal: {kind}")

        save_profiles(profiles)
        req["status"] = "approved"
        req["resolved_at"] = _now()
        req["authorized_by"] = authorized_by
        save_requests(reqs)
        _audit("profile_request_approved", request_id=request_id, kind=kind, authorized_by=authorized_by)
        return dict(req)


def deny_request(request_id: str, authorized_by: str = "local_user", reason: str = "") -> Dict[str, Any]:
    with _LOCK:
        reqs = load_requests()
        req = next((r for r in reqs.get("requests", []) if r.get("request_id") == request_id), None)
        if not req:
            raise KeyError(f"Request tidak ditemukan: {request_id}")
        if req.get("status") != "pending_user_approval":
            raise ValueError("Request ini tidak lagi pending.")
        req["status"] = "denied"
        req["resolved_at"] = _now()
        req["authorized_by"] = authorized_by
        req["reason"] = reason
        save_requests(reqs)
        _audit("profile_request_denied", request_id=request_id, kind=req.get("kind"), authorized_by=authorized_by, reason=reason)
        return dict(req)


def default_profile_name() -> str:
    data = load_profiles()
    name = data.get("active_profile")
    if not name:
        raise RuntimeError("Belum ada default profile.")
    return str(name)


def default_profile() -> Dict[str, Any]:
    return get_profile(default_profile_name())


def switch_default_profile(name: str) -> Dict[str, Any]:
    """Change the global default used only when a NEW session is created."""
    with _LOCK:
        p = get_profile(name)
        if not p.get("enabled", True):
            raise ValueError("Profile dinonaktifkan.")
        data = load_profiles()
        old = data.get("active_profile")
        data["active_profile"] = name
        save_profiles(data)
        _audit("default_profile_switched", old_profile=old, new_profile=name)
        return p


def switch_profile(name: str) -> Dict[str, Any]:
    """Backward-compatible alias for changing the global default profile."""
    return switch_default_profile(name)


def active_profile() -> Dict[str, Any]:
    """Return the profile bound to this execution context, else the global default."""
    bound = BOUND_PROFILE.get()
    if bound is not None:
        return dict(bound)
    return default_profile()

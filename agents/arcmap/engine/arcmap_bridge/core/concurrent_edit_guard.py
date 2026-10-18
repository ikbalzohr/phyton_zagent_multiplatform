# -*- coding: utf-8 -*-
"""ARC-08: cooperative human/agent edit lease for the ArcMap bridge.

An unannounced mouse edit cannot be locked by this module. The user must
explicitly acquire a human-edit lease; bridge mutations then fail closed.
"""
import threading
import time
import uuid

_LOCK = threading.RLock()
_HUMAN = None
READ_PREFIXES = ("get_", "list_", "inspect_", "describe_", "preview_",
                 "check_", "validate_", "analyze_", "query_", "suggest_")
READ_ACTIONS = set(("ping", "status", "refresh", "edit_guard_status",
                    "edit_guard_acquire", "edit_guard_release"))


def identity(command):
    ctx = command.get("correlation") or {}
    return tuple(str(ctx.get(k) or "") for k in
                 ("principal_id", "workspace_id", "device_id", "resource_id"))


def active():
    global _HUMAN
    if _HUMAN and time.time() >= _HUMAN["expires_at"]:
        _HUMAN = None
    return _HUMAN


def acquire(command):
    global _HUMAN
    owner = identity(command)
    if not all(owner):
        return {"ok": False, "code": "PRINCIPAL_RESOURCE_IDENTITY_REQUIRED"}
    seconds = int(command.get("seconds", 900))
    if not 1 <= seconds <= 7200:
        return {"ok": False, "code": "INVALID_LEASE"}
    with _LOCK:
        if active():
            return {"ok": False, "code": "HUMAN_EDIT_ALREADY_ACTIVE"}
        _HUMAN = {"owner": owner, "token": uuid.uuid4().hex,
                  "expires_at": time.time() + seconds}
        return {"ok": True, "token": _HUMAN["token"],
                "expires_at": _HUMAN["expires_at"], "cooperative_only": True}


def release(command):
    global _HUMAN
    with _LOCK:
        lease = active()
        if not lease:
            return {"ok": False, "code": "NO_ACTIVE_HUMAN_EDIT"}
        if lease["owner"] != identity(command) or (
                lease["token"] != str(command.get("token") or "")):
            return {"ok": False, "code": "EDIT_GUARD_OWNER_MISMATCH"}
        _HUMAN = None
    return {"ok": True, "released": True}


def status(command):
    with _LOCK:
        lease = active()
        return {"ok": True, "human_edit_active": bool(lease),
                "expires_at": lease["expires_at"] if lease else None,
                "cooperative_only": True}


def reject_mutation(command):
    name = str(command.get("action") or "")
    if name in READ_ACTIONS or name.startswith(READ_PREFIXES):
        return None
    with _LOCK:
        lease = active()
        if lease:
            return {"ok": False, "blocked": True,
                    "code": "HUMAN_EDIT_IN_PROGRESS",
                    "expires_at": lease["expires_at"]}
    return None

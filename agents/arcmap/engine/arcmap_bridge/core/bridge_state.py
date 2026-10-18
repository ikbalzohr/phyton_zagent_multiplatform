# -*- coding: utf-8 -*-
"""Process/document identity for the in-process, UI-thread ArcMap bridge."""
import os
import time
import uuid

INSTANCE_ID = uuid.uuid4().hex
DOCUMENT_ID = uuid.uuid4().hex
_DOCUMENT_PATH = None

def document_changed():
    global DOCUMENT_ID, _DOCUMENT_PATH
    DOCUMENT_ID = uuid.uuid4().hex
    _DOCUMENT_PATH = None

def context(mxd=None):
    global DOCUMENT_ID, _DOCUMENT_PATH
    if mxd is None:
        from .current_map import get_mxd
        mxd = get_mxd()
    try:
        path = mxd.filePath or ""
    except Exception:
        path = ""
    normalized = os.path.normcase(path)
    if _DOCUMENT_PATH is not None and normalized != _DOCUMENT_PATH:
        DOCUMENT_ID = uuid.uuid4().hex
    _DOCUMENT_PATH = normalized
    return {"bridge_instance_id": INSTANCE_ID, "document_id": DOCUMENT_ID,
            "document_path": path, "pid": os.getpid()}

def validate(command):
    deadline = command.get("expires_at_epoch")
    if not isinstance(deadline, (int, float)) or time.time() >= deadline:
        return {"ok": False, "code": "COMMAND_EXPIRED",
                "error": "Missing/expired deadline; command was not executed."}
    if command.get("action") in ("ping", "status"):
        return None
    expected = command.get("_expected_context") or {}
    actual = context()
    for key in ("bridge_instance_id", "document_id"):
        if not expected.get(key) or expected[key] != actual[key]:
            return {"ok": False, "code": "CURRENT_MXD_CHANGED",
                    "error": "Bridge or CURRENT-MXD changed; inspect again before retrying.",
                    "expected": expected, "actual": actual}
    return None

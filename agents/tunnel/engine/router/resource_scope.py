"""Trusted optional per-file scheduling for narrow Files mutations.

This is a *second* lock nested inside installation shared lease. It must not
be used for deletion, directory mutation, commands, QGIS or unknown actions.
Alias checks and canonical path authorization still belong to Files engine.
"""
from __future__ import annotations
import hashlib
import re

_SIMPLE_FILE_MUTATIONS = frozenset({"files_write", "files_patch", "files_append"})
_NAME = re.compile(r"^[A-Za-z0-9 _.,@()+\-]{1,160}$")


def scoped_write_key(context, service_id, tool_name, arguments):
    """Return a secondary resource key only for independently scoped file writes.

    The caller must hold installation READ while this key is held WRITE;
    all non-scoped mutations retain installation WRITE. The original journal
    resource_key remains unchanged for historical/quarantine inspection.
    """
    if service_id not in {"zagent_files", "zagent_files_v3"} or tool_name not in _SIMPLE_FILE_MUTATIONS:
        return None
    if not isinstance(context, dict) or not isinstance(arguments, dict):
        return None
    if context.get("context_version") != 1 or context.get("public_tool") != tool_name:
        return None
    if context.get("required_scope") != "files:write" or context.get("effective_access") != "write":
        return None
    resources = context.get("effective_resources")
    if not isinstance(resources, list) or len(resources) != 1 or not isinstance(resources[0], dict):
        return None
    item = resources[0]
    if item.get("kind") != "files" or not isinstance(item.get("resource_id"), str):
        return None
    if not item["resource_id"] or not isinstance(item.get("profile_id"), str) or not item["profile_id"]:
        return None
    raw = arguments.get("path")
    if not isinstance(raw, str) or not 1 <= len(raw) <= 512:
        return None
    # Reject absolute/drive/UNC paths and ambiguous path forms. Reduce scope only
    # for boring, existing-like relative paths. Complex Windows names fall back
    # to exclusive installation locking (not an authorization decision).
    if (raw[0] in "\\/" or ":" in raw or "\x00" in raw or
            raw.endswith(("/", "\\")) or "//" in raw or "\\\\" in raw):
        return None
    parts = raw.replace("\\", "/").split("/")
    if any(x in ("", ".", "..") or not _NAME.fullmatch(x) for x in parts):
        return None
    canonical = "/".join(p.casefold().rstrip(" .") for p in parts)
    if not canonical or any(not x for x in canonical.split("/")):
        return None
    # Stable hash hides paths from scheduler resource keys/log records.
    reference = "\x1f".join([context.get("installation_id", ""),
                                 item["resource_id"], item["profile_id"], canonical])
    return "filespath:" + hashlib.sha256(reference.encode("utf-8")).hexdigest()

"""Conservative, service-scoped quarantine for interrupted MCP tasks.

An old installation-wide scheduler lease is NOT evidence that every agent
mutates the same resource. Quarantine only a resource family that might have
overlapping effects. Unknown services and multi-agent workflows fail closed.

Historical task records and their audit trail are never edited here.
"""
from __future__ import annotations

import json
from typing import Mapping, Any

# Each family owns mutable state independently. QGIS currently executes through
# Files owner-command authority and may touch files in approved profiles.
_FAMILY = {
    "zagent_files": "files",
    "zagent_files_v3": "files",
    "zagent_qgis": "files",
    "zagent_arcmap": "arcmap",
    "zagent_web": "browser",
}

# Explicit, reviewed no-effect probes only: do not infer read-only from a
# task's scheduler access_mode (legacy commands were all scheduled as write).
_SAFE_PROBES = {
    ("zagent_arcmap", "arcmap_ping"): (frozenset({"arcmap:inspect", "arcmap:execute"}), "arcmap"),
}


def nonblocking_probe(row: Mapping[str, Any]) -> bool:
    """True only for a canonically identified no-effect ArcMap ping."""
    expected = _SAFE_PROBES.get((row.get("service_id"), row.get("tool_name")))
    if not expected:
        return False
    try:
        context = json.loads(row.get("execution_context_json") or "{}")
        args = json.loads(row.get("arguments_json") or "{}")
    except (ValueError, TypeError):
        return False
    scopes, kind = expected
    resources = context.get("effective_resources")
    return (
        type(context.get("context_version")) is int
        and context["context_version"] == 1
        and context.get("public_tool") == row.get("tool_name")
        and context.get("required_scope") in scopes
        and isinstance(resources, list)
        and len(resources) == 1
        and isinstance(resources[0], dict)
        and resources[0].get("kind") == kind
        and isinstance(context.get("installation_id"), str)
        and row.get("resource_key") == "installation:" + context["installation_id"]
        and resources[0].get("resource_id") == row["resource_key"]
        and row.get("target_device_id")
        and context.get("device_id") == row.get("target_device_id") == row.get("executed_on")
        and args == {}
    )


def blocks_service(row: Mapping[str, Any], target_service: str) -> bool:
    """Determine whether an interrupted operation may affect this service.

    A valid historical no-effect probe never quarantines commands. Writers and
    ambiguous observations still block their own resource family. Workflows,
    unrecognized services and unknown families conservatively block everyone.
    """
    if nonblocking_probe(row):
        return False
    source_service = row.get("service_id")
    source = _FAMILY.get(source_service)
    target = _FAMILY.get(target_service)
    if source is None or target is None:
        return True
    tool = row.get("tool_name")
    # A mismatched persisted service/tool pair has no trustworthy domain.
    # Conservatively quarantine it instead of trusting the service label.
    prefix = "qgis_" if source_service == "zagent_qgis" else (
        "files_" if source == "files" else
        "arcmap_" if source == "arcmap" else "web_")
    if not isinstance(tool, str) or not tool.startswith(prefix):
        return True
    return source == target

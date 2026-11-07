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
    ("zagent_arcmap", "arcmap_execution_capabilities"): (
        frozenset({"arcmap:inspect", "arcmap:execute"}), "arcmap"),
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

# Explicitly reviewed, non-mutating Files tools.  Never infer observational
# semantics from a "read" prefix or caller-provided scheduler access_mode.
_FILES_OBSERVATIONS = frozenset({
    "files_ping", "files_runtime_info", "files_get_root",
    "files_exists", "files_list", "files_tree", "files_stat",
    "files_read", "files_read_bytes_b64", "files_search", "files_hash",
    "files_diff", "files_backup_list", "files_syntax_check",
    "files_project_instructions", "files_workspace_status",
    "files_workspace_list", "files_operation_status", "files_operation_list",
    "files_capabilities", "files_allowlist_list",
})


def safe_read_target(service: str, tool: str, context: Mapping[str, Any]) -> bool:
    """Permit independently authorized observations despite an uncertain write.

    This only relaxes the *orphan conflict* gate. Live OAuth/grant, mapping,
    profile-generation, device and deadline validation still execute normally.
    The historical task and its quarantine for writes remain untouched.
    """
    if (not isinstance(context, Mapping)
            or type(context.get("context_version")) is not int
            or context["context_version"] != 1
            or context.get("public_tool") != tool):
        return False
    resources = context.get("effective_resources")
    if (not isinstance(resources, list) or len(resources) != 1
            or not isinstance(resources[0], dict)
            or not isinstance(context.get("installation_id"), str)
            or not context["installation_id"]
            or not isinstance(context.get("device_id"), str)
            or not context["device_id"]):
        return False
    resource = resources[0]
    if service in {"zagent_files", "zagent_files_v3"}:
        return (
            tool in _FILES_OBSERVATIONS
            and context.get("required_scope") == "files:read"
            and context.get("effective_access") == "read"
            and resource.get("kind") == "files"
            and isinstance(resource.get("resource_id"), str)
            and bool(resource["resource_id"])
            and isinstance(resource.get("profile_id"), str)
            and bool(resource["profile_id"])
        )
    if service == "zagent_arcmap" and tool in {"arcmap_ping", "arcmap_execution_capabilities"}:
        return (
            context.get("required_scope") in {"arcmap:inspect", "arcmap:execute"}
            and resource == {
                "kind": "arcmap",
                "resource_id": "installation:" + context["installation_id"],
            }
        )
    return False

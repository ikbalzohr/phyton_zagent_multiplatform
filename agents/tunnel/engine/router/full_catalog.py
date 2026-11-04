"""Opt-in tool-policy defaults for already-discovered Multi Platform MCP tools.

No server discovery, no remote grants and no OAuth scopes are created here.
The owner must independently configure catalogue mode, bearer token scopes,
principal grant and locally approved Files profile/command policy.
"""
from __future__ import annotations

from .files_policy import FILES_TOOL_SCOPES
from .profile_admin import PROFILE_ADMIN_SCOPES

# Owner operations are still gated by their existing source-level capabilities.
_MANAGEMENT_SCOPES = {
    "zagent_task_submit": "files:write",
    "zagent_artifact_read": "files:read",
    "zagent_allowlist_access": "files:write",
    "zagent_task_recover": "files:write",
    "zagent_workflow_status": "arcmap:inspect",
    "zagent_workflow_report": "arcmap:inspect",
    "zagent_workflow_cancel": "arcmap:execute",
}


def inferred_policy(name: str, registry) -> dict | None:
    """Return a canonical policy only for a real, enabled discovered tool."""
    if name in _MANAGEMENT_SCOPES:
        return {"scope": _MANAGEMENT_SCOPES[name], "enabled": True}
    mapping = registry.tool_index.get(name)
    if mapping is None:
        return None
    service_id, upstream = mapping
    state = registry.states.get(service_id)
    if state is None or not state.service.get("enabled", True):
        return None
    namespace = state.service.get("namespace")
    if name != (upstream if upstream.startswith(namespace + "_") else namespace + "_" + upstream):
        return None
    if service_id in {"zagent_files", "zagent_files_v3"} and namespace == "files":
        scope = FILES_TOOL_SCOPES.get(name) or PROFILE_ADMIN_SCOPES.get(name)
        return {"scope": scope, "enabled": True} if scope else None
    if namespace == "web" and service_id == "zagent_web":
        return {"scope": "web:control", "enabled": True}
    if namespace == "arcmap" and service_id == "zagent_arcmap":
        return {"scope": "arcmap:execute", "enabled": True}
    if namespace == "qgis" and service_id == "zagent_qgis" and state.service.get("internal_auth") is False:
        # QGIS retains its existing files:execute + files:write command authority.
        return {"scope": "files:execute", "enabled": True}
    return None
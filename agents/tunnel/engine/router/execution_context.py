"""Trusted internal execution context v1. Never sourced from client _meta."""
from __future__ import annotations
import time
import uuid
from typing import Any
from .access import AuthContext, AuthorizationError, ResourceAuthorizer, digest
from .identity import Placement
from .files_policy import validate_files_tool_scope
from .files_selection import profile_id

AUTHORITY_FIELDS = frozenset({"_meta", "metadata", "session_id", "owner_session_id",
    "operator_alias", "principal_id", "workspace_id", "grant_id", "scopes", "policy_revision",
    "device_id", "target_device_id", "installation_id", "request_id", "trace_id", "task_id",
    "resource_key", "access_mode", "priority", "fencing_epoch", "lease_owner", "execution_context",
    "effective_resources", "files_resource", "effective_access", "required_scope", "public_tool"})


def reject_authority(arguments: dict[str, Any]) -> None:
    if not isinstance(arguments, dict) or AUTHORITY_FIELDS.intersection(arguments):
        raise ValueError("CLIENT_AUTHORITY_NOT_ALLOWED")


_FILES_WORKSPACE_SELECTORS = frozenset({
    'files_workspace_open', 'files_workspace_status', 'files_workspace_switch',
    'files_operation_status', 'files_operation_cancel', 'files_operation_list',
})


def authority_arguments(tool: str, arguments: dict[str, Any], workspace_id: str) -> dict[str, Any]:
    """Exclude an authenticated same-workspace selector from authority checks only.

    The original payload is untouched and still validated against the tool schema.
    All other tools continue rejecting workspace_id as caller authority.
    """
    if tool in _FILES_WORKSPACE_SELECTORS and 'workspace_id' in arguments:
        if arguments['workspace_id'] != workspace_id:
            raise AuthorizationError('WORKSPACE_SCOPE_MISMATCH', 403)
        return {key: value for key, value in arguments.items() if key != 'workspace_id'}
    return dict(arguments)


_SCOPE_TO_KIND = {
    "files": "files",
    "file": "files",
    "web": "browser",
    "browser": "browser",
    "arcmap": "arcmap",
}


def _kind_from_scope(scope: Any) -> str:
    if not isinstance(scope, str) or ":" not in scope:
        raise AuthorizationError("CONTEXT_INVALID", 403)
    prefix = scope.split(":", 1)[0].strip().lower()
    kind = _SCOPE_TO_KIND.get(prefix)
    if kind is None:
        raise AuthorizationError("CONTEXT_INVALID", 403)
    return kind


def policy_resources(auth: AuthContext, placement: Placement, scope: str,
                     resource_authorizer: ResourceAuthorizer | None = None, *,
                     selected_profile_id: str | None = None, catalog: dict | None = None) -> list[dict[str, str]]:
    kind = _kind_from_scope(scope)
    if kind != "files":
        return [{"resource_id": "installation:"+placement.installation_id, "kind": kind}]
    # Local policy alone supplies approved profiles, never arguments or metadata.
    if resource_authorizer is None:
        raise AuthorizationError("FILES_RESOURCE_NOT_CONFIGURED", 403)
    resource = resource_authorizer.current_grant(auth).get("files_resource")
    if (not isinstance(resource, dict) or resource.get("revoked", False) is not False
            or resource.get("kind") != "files"
            or resource.get("device_id") != placement.device_id
            or resource.get("installation_id") != placement.installation_id
            or not all(isinstance(resource.get(k), str) and resource[k].strip()
                       and len(resource[k]) <= 256 for k in ("resource_id", "profile_id"))):
        raise AuthorizationError("FILES_RESOURCE_NOT_AUTHORIZED", 403)
    default = profile_id(resource['profile_id'])
    allowed = resource.get('allowed_profile_ids', [default])
    if catalog is not None:
        default = profile_id(catalog['default_profile_id'])
        allowed = catalog['allowed_profile_ids']
    if (not isinstance(allowed, list) or not 1 <= len(allowed) <= (512 if catalog is not None else 128)
            or any(profile_id(item) != item for item in allowed)
            or len(set(allowed)) != len(allowed) or (catalog is None and default not in allowed)):
        raise AuthorizationError("FILES_RESOURCE_NOT_AUTHORIZED", 403)
    # The catalog filters disabled/deleted rows. A disabled default blocks
    # omission, not an explicit authorized selection (including queued work).
    if selected_profile_id is None and default not in allowed:
        raise AuthorizationError("FILES_RESOURCE_NOT_AUTHORIZED", 403)
    selected = default if selected_profile_id is None else profile_id(selected_profile_id)
    if selected not in allowed:
        raise AuthorizationError("FILES_RESOURCE_NOT_AUTHORIZED", 403)
    result = {"resource_id": resource['resource_id'], "kind": "files", "profile_id": selected}
    if catalog is not None:
        result['profile_generation'] = catalog['generations'][selected]
    return [result]


def new_context(auth: AuthContext, placement: Placement, scope: str, tool: str,
                lifetime: float = 300, *,
                resource_authorizer: ResourceAuthorizer | None = None,
                selected_profile_id: str | None = None, catalog: dict | None = None) -> dict[str, Any]:
    # Renewing a token does not extend this effect window. Long publish/ArcPy
    # operations need an explicitly provisioned lifetime, not silent extension.
    placement.validate()
    auth.require(scope, tool)
    effective_access = "write"
    if _kind_from_scope(scope) == "files" or tool.startswith("files_"):
        effective_access = validate_files_tool_scope(tool, scope, auth.scopes)
    elif tool == "arcmap_stage3_health" and scope in ("arcmap:inspect", "arcmap:execute"):
        # Canonically audited no-effect Stage 3 health probe.
        effective_access = "read"
    resources = policy_resources(auth, placement, scope, resource_authorizer,
                                 selected_profile_id=selected_profile_id, catalog=catalog)
    return {"context_version": 1, "principal_id": auth.principal_id,
        "workspace_id": auth.workspace_id, "device_id": placement.device_id,
        "installation_id": placement.installation_id,
        "request_id": "req_"+uuid.uuid4().hex, "trace_id": "trc_"+uuid.uuid4().hex,
        "operation_id": "op_"+uuid.uuid4().hex, "task_id": "tsk_"+uuid.uuid4().hex,
        "deadline": min(auth.expires_at, time.time()+lifetime),
        "scopes": sorted(auth.scopes), "policy_revision": auth.policy_revision,
        # Typed object shape matching consumers B (files/web/arcmap) and producer C
        # (InternalManagementChannel): {resource_id, kind, profile_id?}.
        "effective_resources": resources,
        "effective_access": effective_access, "required_scope": scope, "public_tool": tool}


def scheduler_meta(context: dict[str, Any], owner: str, key: str = "", arguments: Any = None) -> dict[str, Any]:
    # Only explicit reviewed read-only tools share the installation reader
    # lease. Never infer a tool's effect type from its name or client args.
    read_only = (context.get("effective_access") == "read" and (
        context.get("required_scope") == "files:read"
        or (context.get("public_tool") == "arcmap_stage3_health"
            and context.get("required_scope") in ("arcmap:inspect", "arcmap:execute"))))
    return {"session_id": owner, "request_id": context["request_id"],
        "trace_id": context["trace_id"], "task_id": context["task_id"],
        "target_device_id": context["device_id"], "executed_on": context["device_id"],
        # Profile policy must not split the existing shared installation lock.
        "resource_key": "installation:"+context["installation_id"],
        "access_mode": "read" if read_only else "write",
        "priority": 1 if read_only else 2,
        "execution_context": context,
        "idempotency_key": digest([owner, context["public_tool"], key]) if key else ""}


def validate_context(value: Any, placement: Placement) -> dict[str, Any]:
    if not isinstance(value, dict) or type(value.get("context_version")) is not int or value.get("context_version") != 1:
        raise AuthorizationError("CONTEXT_REQUIRED", 403)
    allowed = {"context_version", "principal_id", "workspace_id", "device_id", "installation_id", "request_id", "trace_id", "task_id", "operation_id", "policy_revision", "required_scope", "public_tool", "run_id", "deadline", "scopes", "effective_resources", "effective_access"}
    if set(value) - allowed:
        raise AuthorizationError("CONTEXT_INVALID", 403)
    for key in ("principal_id", "workspace_id", "device_id", "installation_id", "request_id",
                "trace_id", "task_id", "operation_id", "policy_revision", "required_scope", "public_tool"):
        if not isinstance(value.get(key), str) or not value[key] or len(value[key]) > 512:
            raise AuthorizationError("CONTEXT_INVALID", 403)
    placement.validate(value["device_id"])
    resources = value.get("effective_resources")
    if (not isinstance(resources, list) or not resources or len(resources) > 128
            or not all(isinstance(r, dict)
                      and isinstance(r.get("resource_id"), str) and r.get("resource_id")
                      and isinstance(r.get("kind"), str) and r["kind"] in ("files", "browser", "arcmap")
                      and (r["kind"] != "files" or
                           (isinstance(r.get("profile_id"), str) and r["profile_id"].strip()
                            and len(r["profile_id"]) <= 256))
                      for r in resources)):
        raise AuthorizationError("CONTEXT_INVALID", 403)
    if (value["installation_id"] != placement.installation_id
            or not isinstance(value.get("deadline"), (float, int))
            or not time.time() < value["deadline"] <= time.time()+3600
            or not isinstance(value.get("scopes"), list)
            or not all(isinstance(s, str) for s in value["scopes"])):
        raise AuthorizationError("CONTEXT_INVALID", 403)
    effective_access = "write"
    if (_kind_from_scope(value["required_scope"]) == "files"
            or value["public_tool"].startswith("files_")
            or any(r["kind"] == "files" for r in resources)):
        effective_access = validate_files_tool_scope(
            'files_powershell_run' if value['public_tool'].startswith('qgis_') else value["public_tool"],
            value["required_scope"], value["scopes"])
        if not all(r["kind"] == "files" for r in resources):
            raise AuthorizationError("CONTEXT_INVALID", 403)
    elif (value["public_tool"] == "arcmap_stage3_health"
          and value["required_scope"] in ("arcmap:inspect", "arcmap:execute")
          and len(resources) == 1 and resources[0]["kind"] == "arcmap"
          and resources[0]["resource_id"] == "installation:" + value["installation_id"]):
        effective_access = "read"
    if value.get("effective_access") != effective_access:
        raise AuthorizationError("CONTEXT_INVALID", 403)
    return dict(value)

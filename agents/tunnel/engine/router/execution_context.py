"""Trusted internal execution context v1. Never sourced from client _meta."""
from __future__ import annotations
import time
import uuid
from typing import Any
from .access import AuthContext, AuthorizationError, digest
from .identity import Placement

AUTHORITY_FIELDS = frozenset({"_meta", "metadata", "session_id", "owner_session_id",
    "operator_alias", "principal_id", "workspace_id", "grant_id", "scopes", "policy_revision",
    "device_id", "target_device_id", "installation_id", "request_id", "trace_id", "task_id",
    "resource_key", "access_mode", "priority", "fencing_epoch", "lease_owner", "execution_context"})


def reject_authority(arguments: dict[str, Any]) -> None:
    if not isinstance(arguments, dict) or AUTHORITY_FIELDS.intersection(arguments):
        raise ValueError("CLIENT_AUTHORITY_NOT_ALLOWED")


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


def new_context(auth: AuthContext, placement: Placement, scope: str, tool: str,
                lifetime: float = 300) -> dict[str, Any]:
    # Renewing a token does not extend this effect window. Long publish/ArcPy
    # operations need an explicitly provisioned lifetime, not silent extension.
    placement.validate()
    auth.require(scope, tool)
    kind = _kind_from_scope(scope)
    return {"context_version": 1, "principal_id": auth.principal_id,
        "workspace_id": auth.workspace_id, "device_id": placement.device_id,
        "installation_id": placement.installation_id,
        "request_id": "req_"+uuid.uuid4().hex, "trace_id": "trc_"+uuid.uuid4().hex,
        "operation_id": "op_"+uuid.uuid4().hex, "task_id": "tsk_"+uuid.uuid4().hex,
        "deadline": min(auth.expires_at, time.time()+lifetime),
        "scopes": sorted(auth.scopes), "policy_revision": auth.policy_revision,
        # Typed object shape matching consumers B (files/web/arcmap) and producer C
        # (InternalManagementChannel): {resource_id, kind, profile_id?}.
        "effective_resources": [{"resource_id": "installation:"+placement.installation_id,
                                "kind": kind}],
        "effective_access": "write", "required_scope": scope, "public_tool": tool}


def scheduler_meta(context: dict[str, Any], owner: str, key: str = "", arguments: Any = None) -> dict[str, Any]:
    return {"session_id": owner, "request_id": context["request_id"],
        "trace_id": context["trace_id"], "task_id": context["task_id"],
        "target_device_id": context["device_id"], "executed_on": context["device_id"],
        "resource_key": context["effective_resources"][0]["resource_id"], "access_mode": "write", "priority": 2,
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
                      for r in resources)):
        raise AuthorizationError("CONTEXT_INVALID", 403)
    if (value["installation_id"] != placement.installation_id
            or not isinstance(value.get("deadline"), (float, int))
            or not time.time() < value["deadline"] <= time.time()+3600
            or not isinstance(value.get("scopes"), list)
            or not all(isinstance(s, str) for s in value["scopes"])
            or value.get("effective_access") != "write"):
        raise AuthorizationError("CONTEXT_INVALID", 403)
    return dict(value)

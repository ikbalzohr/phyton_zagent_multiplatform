"""Tunnel1: one authenticated, stateless MCP perimeter over existing journals.

Only /mcp and RFC9728 metadata are public. /router is an authenticated local
channel, never a second remote API. No authorization-server endpoints live here.
"""
from __future__ import annotations

import asyncio
import json
import os
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import httpx
import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response
from jsonschema import Draft202012Validator

from .access import AuthContext, AuthorizationError, ResourceAuthorizer, owner_key
from .diagnostics import public_error
from .diagnostic_events import CURRENT_ID, new_request_id, request_id, record, failure_code, traced
from .artifacts import read_artifact
from .config import load_tunnel_config
from .execution_context import authority_arguments, new_context, policy_resources, reject_authority, scheduler_meta, validate_context
from .files_policy import scope_for_files_tool, validate_files_tool_scope
from .files_selection import files_tool_schema, selected_profile
from .files_policy import FILES_TOOL_SCOPES
from .profile_admin import (PROFILE_ADMIN_SCOPES, require_profile_management, catalog_context,
                            validate_catalog, new_admin_context, revalidate_admin)
from .identity import Placement, internal_token, verify_internal_token
from .orchestration import Orchestrator, PreDispatchRejected
from .registry import MCPRegistry
from .workflow_domain import WorkflowDomainJournal
from .workflow_runtime import WorkflowRuntimeService
from .workflow_security import execution_authority

SERVER_INFO = {"name": "Zagent Tunnel", "version": "1.0.0"}
PROTOCOL = "2025-11-25"  # candidate; client conformance NOT_RUN
SERVER_INSTRUCTIONS = "Authenticated workspace operations. Durable jobs survive disconnect, not authorization expiry. Cancellation does not undo side effects."
registry = MCPRegistry()
placement = Placement(os.environ.get("ZAGENT_DEVICE_ID", ""), os.environ.get("ZAGENT_INSTALLATION_ID", ""))
# Bearers live only in memory, bounded and never journaled or returned.
_credentials: dict[str, tuple[str, float]] = {}
_auth_client: httpx.AsyncClient | None = None


def authorizer() -> ResourceAuthorizer:
    return ResourceAuthorizer(load_tunnel_config().get("resource_server") or {})


_NATIVE_ALLOWLIST_TOOLS = frozenset({"files_allowlist_list", "files_allowlist_add",
    "files_allowlist_remove", "files_allowlist_replace"})


def _policy(name: str) -> dict[str, Any]:
    policies = load_tunnel_config().get("tool_policy")
    if policies is None:
        policies = {}
    if not isinstance(policies, dict):
        raise AuthorizationError("TOOL_NOT_AUTHORIZED", 403)
    # Only the new native tools have defaults. An explicit entry, even malformed
    # or disabled, must never fall back to an enabled policy.
    if name not in policies and name in _NATIVE_ALLOWLIST_TOOLS:
        return {"scope": scope_for_files_tool(name), "enabled": True}
    policy = policies.get(name)
    if not isinstance(policy, dict) or not policy.get("scope"):
        raise AuthorizationError("TOOL_NOT_AUTHORIZED", 403)
    if name.startswith("files_") and policy["scope"] != scope_for_files_tool(name):
        raise AuthorizationError("FILES_TOOL_SCOPE_MISMATCH", 403)
    return policy


_SKIP = {"zagent_access_status", "zagent_capabilities"}
_ALWAYS = {"zagent_task_list", "zagent_task_status", "zagent_task_result", "zagent_task_cancel"}
# Scoped command controls must remain reachable while the installation lock is
# held by their target. These are not arbitrary filesystem mutation shortcuts.
_FILES_IMMEDIATE_CONTROLS = frozenset({"files_command_cancel", "files_command_capabilities",
    "files_process_list", "files_process_stop"})
# Plan/validate/read/cancel remain available; execution must not be advertised
# while the optional engine's artifact integrity component is absent.
_WORKFLOW_EXECUTION_TOOLS = {"arcmap_goal_execute", "arcmap_goal_build_map", "arcmap_goal_resume"}


def _remember(context: dict[str, Any], bearer: str) -> None:
    stamp = time.time()
    for key, (_, expiry) in list(_credentials.items()):
        if expiry <= stamp:
            _credentials.pop(key, None)
    if len(_credentials) >= 4096:
        raise AuthorizationError("OVERLOADED", 429)
    _credentials[context["request_id"]] = (bearer, context["deadline"])


async def _revalidate(context: dict[str, Any]) -> AuthContext:
    is_admin = context.get('public_tool') in PROFILE_ADMIN_SCOPES
    if not is_admin:
        context = validate_context(context, placement)
    entry = _credentials.get(context["request_id"])
    if entry is None or entry[1] <= time.time() or _auth_client is None:
        raise AuthorizationError("AUTHORIZATION_EXPIRED", 403)
    current_authorizer = authorizer()
    auth = await current_authorizer.authenticate(entry[0], _auth_client)
    if (auth.principal_id != context["principal_id"] or auth.workspace_id != context["workspace_id"]
            or auth.policy_revision != context["policy_revision"]):
        raise AuthorizationError("AUTHORIZATION_CHANGED", 403)
    auth.require(context["required_scope"], context["public_tool"])
    if is_admin:
        revalidate_admin(context, auth, placement, current_authorizer)
    if context["public_tool"].startswith("files_"):
        validate_files_tool_scope(context["public_tool"], context["required_scope"], auth.scopes)
    if not is_admin and context["effective_resources"] != policy_resources(
            auth, placement, context["required_scope"], current_authorizer,
            selected_profile_id=context["effective_resources"][0]["profile_id"]
            if context["effective_resources"][0]['kind'] == 'files' else None,
            catalog=await _files_catalog(auth, current_authorizer)
            if context['public_tool'] in FILES_TOOL_SCOPES else None):
        raise AuthorizationError("AUTHORIZATION_CHANGED", 403)
    try:
        policy = _policy(context["public_tool"])
    except AuthorizationError:
        policy = {"scope": context["required_scope"], "enabled": False}
    if policy["scope"] != context["required_scope"] or policy.get("enabled", True) is not True:
        raise AuthorizationError("AUTHORIZATION_CHANGED", 403)
    return auth


async def _files_catalog(auth, current_authorizer):
    current_authorizer.current_grant(auth)
    snapshot = await registry.profile_catalog_snapshot(catalog_context(auth, placement))
    return validate_catalog(snapshot, auth, placement, current_authorizer)


async def _request_context(auth, policy, name, arguments):
    current_authorizer = authorizer()
    if name in PROFILE_ADMIN_SCOPES:
        return new_admin_context(auth, placement, current_authorizer, name, arguments)
    catalog = await _files_catalog(auth, current_authorizer) if name in FILES_TOOL_SCOPES else None
    return new_context(auth, placement, policy['scope'], name,
                       resource_authorizer=current_authorizer,
                       selected_profile_id=selected_profile(name, arguments), catalog=catalog)


async def _executor(service: str, tool: str, arguments: dict[str, Any], ctx):
    try:
        async with orchestrator.journal._lock:
            isolated = orchestrator.journal.conn.execute("SELECT 1 FROM tasks WHERE resource_key=? AND state='orphaned' AND started_at IS NOT NULL AND task_id<>? LIMIT 1", (ctx.resource_key, ctx.task_id)).fetchone()
        if isolated and tool not in _FILES_IMMEDIATE_CONTROLS:
            raise AuthorizationError("RESOURCE_RECONCILIATION_REQUIRED", 409)
        auth = await _revalidate(ctx.execution_context)
        if ctx.session_id != auth.owner:
            raise AuthorizationError("OWNER_MISMATCH", 403)
        placement.validate(ctx.target_device_id)
    except AuthorizationError as exc:
        raise PreDispatchRejected(str(exc)) from exc
    if service == "__workflow__":
        loop = asyncio.get_running_loop()
        def authorize_step():
            future = asyncio.run_coroutine_threadsafe(_revalidate(ctx.execution_context), loop)
            future.result(timeout=7)
        with execution_authority(ctx.execution_context, authorize_step):
            return await workflow_runtime.execute_internal(tool, arguments, ctx)
    try:
        configured = _policy(ctx.execution_context["public_tool"])
        workflow_validation = (ctx.execution_context.get("run_id") and service == "zagent_arcmap" and tool == "arcmap_goal_validate")
        if not workflow_validation and registry.get_mapping(ctx.execution_context["public_tool"]) != (service, tool):
            raise AuthorizationError("TOOL_MAPPING_CHANGED", 403)
        if configured.get("enabled", True) is not True:
            raise AuthorizationError("TOOL_NOT_AUTHORIZED", 403)
    except AuthorizationError as exc:
        raise PreDispatchRejected(str(exc)) from exc
    return await registry.invoke(service, tool, arguments, ctx)


orchestrator = Orchestrator(_executor)
_runtime = Path(os.environ.get("ZAGENT_TUNNEL_RUNTIME_DIR", str(Path(__file__).resolve().parents[1]/"runtime")))
workflow_journal = WorkflowDomainJournal(_runtime/"workflow_tasks.db")
workflow_runtime = WorkflowRuntimeService(workflow_journal, orchestrator, device_id=placement.device_id)


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _auth_client
    _auth_client = httpx.AsyncClient(trust_env=False, follow_redirects=False)
    try:
        cfg = load_tunnel_config().get("orchestration", {})
        orchestrator.configure(cfg)
        workflow_journal.recover_incomplete_runs()
        # Discovery is private and requires provisioned internal channel credentials.
        try:
            internal_token()
            await registry.refresh_all()
        except AuthorizationError:
            pass
        await orchestrator.start()
        yield
    finally:
        await orchestrator.stop()
        await registry.close()
        await _auth_client.aclose()
        _auth_client = None
        _credentials.clear()


app = FastAPI(title="Zagent Tunnel1", version="1.0.0", lifespan=lifespan,
              docs_url=None, redoc_url=None, openapi_url=None)


def _auth_error(exc: AuthorizationError) -> JSONResponse:
    correlation = request_id()
    record('auth.rejection', failure_code(exc, 'AUTH_NOT_AUTHORIZED'), correlation)
    headers = {"Cache-Control": "no-store"}
    resource = authorizer().config.get("resource_uri", "")
    if resource.startswith("https://"):
        from urllib.parse import urlsplit
        p = urlsplit(resource)
        metadata = p.scheme+"://"+p.netloc+"/.well-known/oauth-protected-resource"
        if exc.status in (401, 403):
            headers["WWW-Authenticate"] = 'Bearer resource_metadata="'+metadata+'", error="'+("insufficient_scope" if exc.status == 403 else "invalid_token")+'"'
    return JSONResponse({"error": {**public_error(exc.code), 'data': {'requestId': correlation}}}, status_code=exc.status, headers=headers)


@app.middleware("http")
async def boundary(request: Request, call_next):
    correlation = new_request_id()
    token = CURRENT_ID.set(correlation)
    stage = 'router.configuration'
    try:
        cfg = load_tunnel_config()
        origin = request.headers.get("origin")
        if origin is not None and origin not in cfg.get("allowed_origins", []):
            raise AuthorizationError("ORIGIN_DENIED", 403)
        if request.url.path.startswith("/router/"):
            if not request.client or request.client.host not in {"127.0.0.1", "::1"}:
                raise AuthorizationError("INTERNAL_ACCESS_DENIED", 403)
            verify_internal_token(request.headers.get("x-zagent-internal-token", ""))
            request.state.internal = True
        if request.url.path == "/mcp":
            stage = 'auth.token'
            if _auth_client is None:
                raise AuthorizationError("NOT_READY", 503)
            request.state.auth = await authorizer().authenticate(request.headers.get("authorization", ""), _auth_client)
        if request.url.path in ("/broker/allowlist", "/broker/allowlist/catalog"):
            if _auth_client is None:
                raise AuthorizationError("NOT_READY", 503)
            request.state.auth = await authorizer().authenticate(request.headers.get("authorization", ""), _auth_client)
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        return response
    except AuthorizationError as exc:
        record(stage, failure_code(exc, 'AUTH_NOT_AUTHORIZED'))
        return _auth_error(exc)
    except (OSError, ValueError, TypeError):
        record(stage, 'ROUTER_CONFIGURATION_ERROR')
        return JSONResponse({"error":{"code":"CONFIGURATION_INVALID", 'data': {'requestId': correlation}}}, status_code=503)
    except Exception:
        record(stage, 'UNEXPECTED_ERROR')
        return JSONResponse({'error': {'code': 'REQUEST_FAILED', 'data': {'requestId': correlation}}}, status_code=500)
    finally:
        CURRENT_ID.reset(token)


async def bounded_json(request: Request) -> dict[str, Any]:
    if "application/json" not in request.headers.get("content-type", "").lower():
        raise ValueError("JSON_REQUIRED")
    maximum = 1024*1024
    data = bytearray()
    async for chunk in request.stream():
        data.extend(chunk)
        if len(data) > maximum:
            raise AuthorizationError("PAYLOAD_TOO_LARGE", 413)
    body = json.loads(data, parse_constant=lambda _: (_ for _ in ()).throw(ValueError("NONFINITE_NUMBER")))
    if not isinstance(body, dict):
        raise ValueError("OBJECT_REQUIRED_BATCH_UNSUPPORTED")
    return body


def rpc_result(req_id: Any, result: Any):
    return JSONResponse({"jsonrpc":"2.0", "id": req_id, "result":result})


def rpc_error(req_id: Any, code: int, message: str, stage='mcp.protocol'):
    correlation = request_id()
    record(stage, 'UNEXPECTED_ERROR' if code == -32603 else 'ROUTER_PROTOCOL_ERROR', correlation)
    return JSONResponse({"jsonrpc":"2.0", "id":req_id, "error":{"code":code,"message":message, 'data': {'requestId': correlation}}})


def _text(value: Any) -> dict[str, Any]:
    failed = isinstance(value, dict) and (value.get("ok") is False or value.get("isError") is True)
    return {"content":[{"type":"text", "text":json.dumps(value, ensure_ascii=False)}], "isError":failed}


def _tool(name: str, properties=None, required=()):
    return {"name":name, "description":"Authorized workspace "+name.removeprefix("zagent_").replace("_", " "),
        "inputSchema":{"type":"object","properties":properties or {},"required":list(required),"additionalProperties":False}}


def _management_tools():
    string = {"type":"string", "minLength":1,"maxLength":512}
    return [_tool("zagent_access_status"), _tool("zagent_capabilities"),
        _tool("zagent_task_submit", {"tool_name":string,"arguments":{"type":"object"},"idempotency_key":string}, ("tool_name",)),
        *[_tool("zagent_task_"+name, {"task_id":string}, ("task_id",)) for name in ("status","result","cancel")],
        _tool("zagent_task_list", {"limit":{"type":"integer","minimum":1,"maximum":200}}),
        _tool("zagent_artifact_read", {"artifact_id":string,"offset":{"type":"integer","minimum":0},"length":{"type":"integer","minimum":1,"maximum":262144}}, ("artifact_id",)),
        *[_tool("zagent_workflow_"+name, {"run_id":string}, ("run_id",)) for name in ("status","report","cancel")]]


def _visible(auth: AuthContext):
    tools = []
    for tool in [*registry.list_public_tools(), *_management_tools()]:
        tool = files_tool_schema(tool)
        name = tool["name"]
        # Management tools have no upstream mapping (get_mapping would raise).
        mapping = registry.tool_index.get(name)
        upstream_name = mapping[1] if mapping else name
        if upstream_name in _WORKFLOW_EXECUTION_TOOLS and workflow_runtime.execution_unavailable():
            continue
        if name in _SKIP:
            tools.append(tool); continue
        if name in _ALWAYS:
            tools.append(tool); continue
        try:
            policy = _policy(name)
            auth.require(policy["scope"], name)
            if name in PROFILE_ADMIN_SCOPES:
                require_profile_management(auth, placement, authorizer(), name)
            if name.startswith("files_"):
                validate_files_tool_scope(name, policy["scope"], auth.scopes)
            if policy.get("enabled", True) is True:
                if not name.startswith("zagent_"):
                    tool = dict(tool)
                    tool.pop("outputSchema", None)
                    if name in _FILES_IMMEDIATE_CONTROLS:
                        tool["description"] = str(tool.get("description", ""))+" Returns an immediate owned-process control result, not a durable task receipt."
                    else:
                        tool["description"] = str(tool.get("description", ""))+" Returns a durable task receipt; retrieve the domain result with zagent_task_result."
                tools.append(tool)
        except AuthorizationError:
            pass
    return tools


def _validate_tool(name: str, arguments: dict[str, Any], auth: AuthContext):
    tool = next((t for t in _visible(auth) if t["name"] == name), None)
    if tool is None:
        raise AuthorizationError("TOOL_NOT_AUTHORIZED", 403)
    if not name.startswith("zagent_"):
        # Only these cancellation APIs accept task_id as a target selector.
        # It never replaces the authenticated context's task/owner identity.
        selected = authority_arguments(name, arguments, auth.workspace_id)
        if name in {"files_command_cancel", "files_operation_cancel"}:
            selected = {key: value for key, value in selected.items() if key != "task_id"}
        reject_authority(selected)
    Draft202012Validator(tool["inputSchema"]).validate(arguments)
    selected_profile(name, arguments)


async def _owned_task(task_id: str, auth: AuthContext):
    row = await orchestrator.journal.get(task_id)
    if row is None or row.get("session_id") != auth.owner:
        raise KeyError("TASK_NOT_FOUND")
    context = json.loads(row.get("execution_context_json") or "{}")
    public_tool = context.get("public_tool", "")
    policy = _policy(public_tool)
    if policy.get('enabled', True) is not True:
        raise AuthorizationError('TOOL_NOT_AUTHORIZED', 403)
    scope = policy['scope']
    auth.require(scope, public_tool)
    if public_tool in PROFILE_ADMIN_SCOPES:
        # Actor-bound receipts survive target deletion; no profile lookup.
        require_profile_management(auth, placement, authorizer(), public_tool)
        if (context.get('device_id') != placement.device_id
                or context.get('installation_id') != placement.installation_id):
            raise AuthorizationError('AUTHORIZATION_CHANGED', 403)
    elif public_tool.startswith("files_"):
        validate_files_tool_scope(public_tool, scope, auth.scopes)
        # Receipt/result ownership remains principal/workspace, but removed or
        # revoked profile authorization must not expose old paths/results.
        if context.get('effective_resources') != policy_resources(
                auth, placement, scope, authorizer(),
                selected_profile_id=context['effective_resources'][0]['profile_id'],
                catalog=await _files_catalog(auth, authorizer())):
            raise AuthorizationError('AUTHORIZATION_CHANGED', 403)
    return row


async def _dispatch(name: str, arguments: dict[str, Any], auth: AuthContext, bearer: str,
                    key: str = "", submit: bool = False):
    _validate_tool(name, arguments, auth)
    if name == "zagent_access_status":
        return _text({"ok":True, **auth.public()})
    if name == "zagent_capabilities":
        return _text({"ok":True,"version":"1.0.0","tools":[t["name"] for t in _visible(auth)],
                      "workflow_execution_blocker": workflow_runtime.execution_unavailable()})
    # Read-only receipts are authorized against the task owner and ORIGINAL tool.
    # Do not demand extra grant tool names merely to retrieve an approved read.
    # Submission/cancellation retain the separate control-policy checks below.
    if name in {"zagent_task_status", "zagent_task_result", "zagent_task_list"}:
        if name == "zagent_task_list":
            rows = await orchestrator.journal.list(auth.owner, arguments.get("limit", 50))
            visible = []
            for row in rows:
                try:
                    await _owned_task(row["task_id"], auth)
                    visible.append(orchestrator.public_task(row))
                except (AuthorizationError, KeyError):
                    pass
            return _text({"tasks":visible})
        task_id = arguments["task_id"]
        await _owned_task(task_id, auth)
        action = name.removeprefix("zagent_task_")
        return _text(await getattr(orchestrator, action)(task_id))
    policy = _policy(name)
    auth.require(policy["scope"], name)
    if name == "zagent_task_submit":
        target = arguments["tool_name"]
        if target.startswith("zagent_"):
            raise ValueError("UPSTREAM_TOOL_REQUIRED")
        return _text(await _dispatch(target, arguments.get("arguments", {}), auth, bearer,
                                    arguments.get("idempotency_key", ""), True))
    if name == "zagent_artifact_read":
        return _text(await asyncio.to_thread(read_artifact, workflow_journal,
            arguments["artifact_id"], auth.owner,
            load_tunnel_config().get("artifact_roots", []),
            arguments.get("offset", 0), arguments.get("length", 65536)))
    if name == "zagent_task_cancel":
        task_id = arguments["task_id"]
        await _owned_task(task_id, auth)
        return _text(await orchestrator.cancel(task_id))
    if name.startswith("zagent_workflow_"):
        run_id = arguments["run_id"]
        try:
            row = workflow_journal.get_run(run_id, auth.owner)
        except PermissionError:
            row = None
        if row is None:
            raise KeyError("RUN_NOT_FOUND")
        return _text(await getattr(workflow_runtime, name.removeprefix("zagent_workflow_"))(run_id, auth.owner))
    service, upstream = registry.get_mapping(name)
    if name in _FILES_IMMEDIATE_CONTROLS:
        context = await _request_context(auth, policy, name, arguments)
        _remember(context, bearer)
        try:
            control = orchestrator.context(service, upstream,
                scheduler_meta(context, auth.owner, key, arguments), task_id=context["task_id"])
            result = await _executor(service, upstream, arguments, control)
            return result if submit else _text(result)
        finally:
            _credentials.pop(context["request_id"], None)
    async with orchestrator.journal._lock:
        queued = orchestrator.journal.conn.execute("SELECT COUNT(*) FROM tasks WHERE session_id=? AND state IN ('accepted','queued','waiting_capacity','waiting_lock','running','cancelling')", (auth.owner,)).fetchone()[0]
    if queued >= 64 or orchestrator.queue_depth() >= 1024:
        raise AuthorizationError("OVERLOADED", 429)
    context = await _request_context(auth, policy, name, arguments)
    _remember(context, bearer)
    meta = scheduler_meta(context, auth.owner, key, arguments)
    if submit:
        return await orchestrator.submit(service, upstream, arguments, meta)
    # One durable path for mutations too; request disconnect never replays a write.
    receipt = await orchestrator.submit(service, upstream, arguments, meta)
    return _text(receipt)


@app.get("/.well-known/oauth-protected-resource")
async def protected_metadata():
    try:
        return authorizer().metadata()
    except AuthorizationError as exc:
        return _auth_error(exc)


@app.get("/healthz")
async def health():
    return {"service":"Zagent Tunnel", "version":"1.0.0",
            "authorization":"CONFIGURED" if authorizer().configured else "NOT_CONFIGURED"}


@app.api_route("/mcp", methods=["GET", "DELETE"])
async def mcp_unsupported():
    return Response(status_code=405, headers={"Allow":"POST"})


@app.post("/mcp")
@traced('mcp.handler', 'UNEXPECTED_ERROR')
async def mcp(request: Request):
    req_id = None
    stage = 'mcp.request'
    try:
        body = await bounded_json(request)
        req_id, method = body.get("id"), body.get("method")
        params = body.get("params", {})
        if (body.get("jsonrpc") != "2.0" or not isinstance(method, str)
                or not isinstance(params, dict) or isinstance(req_id, (dict, list, bool))):
            return rpc_error(req_id, -32600, "Invalid Request")
        version = request.headers.get("mcp-protocol-version")
        if version and version != PROTOCOL:
            return rpc_error(req_id, -32600, "Unsupported protocol version")
        stage = {'initialize': 'mcp.initialize', 'tools/list': 'mcp.tools_list',
                 'tools/call': 'mcp.tools_call'}.get(method, 'mcp.request')
        if not hasattr(request.state, 'auth'):
            # Missing middleware authority is not anonymous initialization.
            # Preserve the sanitized protocol failure while tagging this gate.
            record('mcp.auth_context', 'AUTH_REQUIRED')
        auth = request.state.auth
        if method == "initialize":
            return rpc_result(req_id, {"protocolVersion":PROTOCOL,"serverInfo":SERVER_INFO,
                "capabilities":{"tools":{}},"instructions":SERVER_INSTRUCTIONS})
        if method == "notifications/initialized":
            return Response(status_code=202)
        if method == "notifications/cancelled":
            # This stateless transport does not attach jobs to RPC IDs. Explicit
            # durable task_cancel is the only cancellation control.
            return Response(status_code=202)
        if "id" not in body:
            return Response(status_code=202)
        if method == "ping":
            return rpc_result(req_id, {})
        if method == "tools/list":
            return rpc_result(req_id, {"tools":_visible(auth)})
        if method == "tools/call":
            name, arguments = params.get("name"), params.get("arguments", {})
            if not isinstance(name, str) or not isinstance(arguments, dict):
                raise ValueError("INVALID_TOOL_ARGUMENTS")
            target = arguments.get('tool_name') if name == 'zagent_task_submit' else name
            if isinstance(target, str) and target in PROFILE_ADMIN_SCOPES and set(params) - {'name', 'arguments'}:
                raise ValueError('PROFILE_ADMIN_PUBLIC_META_DENIED')
            result = await _dispatch(name, arguments, auth, request.headers.get("authorization", ""),
                                     request.headers.get("idempotency-key", ""))
            return rpc_result(req_id, result)
        if method in {"resources/list","resources/templates/list","prompts/list"}:
            key = {"resources/list":"resources", "resources/templates/list":"resourceTemplates", "prompts/list":"prompts"}[method]
            return rpc_result(req_id, {key:[]})
        return rpc_error(req_id, -32601, "Method not found")
    except AuthorizationError as exc:
        record(stage, failure_code(exc, 'AUTH_NOT_AUTHORIZED'))
        return _auth_error(exc)
    except (ValueError, KeyError):
        return rpc_error(req_id, -32602, "Invalid arguments or inaccessible resource", stage)
    except Exception:
        # Validation and backend diagnostics are local; never return traceback,
        # bearer, private topology or file paths as protocol errors.
        return rpc_error(req_id, -32603, "Request failed", stage)


async def _internal_auth(request: Request) -> tuple[dict[str, Any], AuthContext]:
    if not getattr(request.state, "internal", False):
        raise AuthorizationError("INTERNAL_ACCESS_DENIED", 403)
    body = await bounded_json(request)
    context = validate_context(body.get("execution_context"), placement)
    auth = await _revalidate(context)
    return body, auth


@app.get("/router/status")
async def router_status():
    return {**registry.status(), "orchestration":orchestrator.runtime_status()}


@app.get("/router/tasks")
async def router_tasks(limit: int = 50):
    # Core monitoring read model (TunnelManagerReadModel.GetMonitoringAsync).
    # Task rows already carry principal_id/workspace_id via public_task; no
    # raw token/context/arguments/chat IDs are leaked (public_task strips them).
    return await orchestrator.list_tasks(None, limit)


@app.post("/router/tasks/{task_id}/cancel")
async def router_task_cancel(task_id: str, request: Request):
    # Core cancellation (TunnelManagerReadModel.CancelTaskAsync). Internal
    # channel only: loopback + X-Zagent-Internal-Token enforced by middleware.
    try:
        body, auth = await _internal_auth(request)
    except AuthorizationError as exc:
        return _auth_error(exc)
    row = await orchestrator.journal.get(task_id)
    if row is None or row.get("session_id") != auth.owner:
        return JSONResponse({"ok": False, "error": "task not found"}, status_code=404)
    return await orchestrator.cancel(task_id)


@app.get("/router/workflows")
async def router_workflows(principal_id: str = "", workspace_id: str = "", limit: int = 100):
    # Core workflow read model (TunnelManagerReadModel.GetManagementWorkflowsAsync).
    # Map principal_id+workspace_id -> owner_key (owner_v1_...) -> summary.
    owner = owner_key(principal_id, workspace_id)
    return await workflow_runtime.summary(owner, limit)


@app.get("/router/workflows/{run_id}")
async def router_workflow(run_id: str, principal_id: str = "", workspace_id: str = "",
                         report: bool = False):
    owner = owner_key(principal_id, workspace_id)
    if report:
        return await workflow_runtime.report(run_id, owner)
    return await workflow_runtime.status(run_id, owner)


@app.post("/router/refresh")
async def router_refresh():
    registry.reload_config()
    return {"refresh":await registry.refresh_all()}


@app.post("/router/workflows/submit")
async def workflow_submit(request: Request):
    try:
        body, auth = await _internal_auth(request)
        context = body["execution_context"]
        auth.require("arcmap:execute")
        owner = {"session_id":auth.owner, "principal_id":auth.principal_id,
                 "workspace_id":auth.workspace_id,"device_id":placement.device_id,
                 "request_id":context["request_id"],"trace_id":context["trace_id"],
                 "execution_context":context}
        return await workflow_runtime.submit(plan=body.get("plan") or {}, owner=owner,
                    idempotency_key=str(body.get("idempotency_key") or ""), priority=2)
    except AuthorizationError as exc:
        return _auth_error(exc)


@app.post("/router/workflows/{run_id}/{action}")
async def workflow_control(run_id: str, action: str, request: Request):
    try:
        body, auth = await _internal_auth(request)
        if action not in {"status", "report", "cancel"}:
            return JSONResponse({"error":{"code":"NOT_FOUND"}}, status_code=404)
        auth.require("arcmap:execute" if action == "cancel" else "arcmap:inspect")
        return await getattr(workflow_runtime, action)(run_id, auth.owner)
    except AuthorizationError as exc:
        return _auth_error(exc)


from .allowlist_admin import install_routes as _install_allowlist_routes
import sys as _sys
allowlist_routes = _install_allowlist_routes(_sys.modules[__name__])


def run():
    cfg = load_tunnel_config().get("router", {})
    host = cfg.get("host", "127.0.0.1")
    if host not in {"127.0.0.1", "127.0.0.3", "::1"}:
        raise ValueError("Tunnel router must bind loopback; terminate public HTTPS at a provisioned ingress")
    uvicorn.run("router.server:app", host=host, port=int(cfg.get("port",18810)),
                log_level=cfg.get("log_level","info"), reload=False, proxy_headers=False)


if __name__ == "__main__":
    run()

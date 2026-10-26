from __future__ import annotations

import asyncio
import json
import logging
import os
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

import httpx

from .config import load_services, public_tool_name
from .orchestration import ExecContext
from .identity import internal_token
from .files_selection import forward_files_arguments
from .profile_admin import PROFILE_ADMIN_SCOPES, CATALOG_TOOL
from .access import AuthorizationError, digest

log = logging.getLogger("zagent.tunnel.router.registry")

MCP_PROTOCOL_VERSION = "2025-06-18"
CLIENT_INFO = {"name": "Zagent-Tunnel-Router", "version": "1.0.0"}
_DEVICE_ID = os.environ.get("ZAGENT_DEVICE_ID", "").strip()

# Normal MCP traffic should fail fast, but command/build/test tools can legitimately
# run for minutes. Their own timeout_seconds contract is authoritative; the Router
# adds a small transport margin so it does not abandon the task before the agent.
_LONG_CALL_TIMEOUT_MARGIN_SECONDS = 15.0
_MAX_LONG_CALL_TIMEOUT_SECONDS = max(
    30.0,
    min(float(os.environ.get("ZAGENT_MAX_LONG_CALL_TIMEOUT_SECONDS", "1830")), 7200.0),
)


def _tool_call_timeout_seconds(
    state: "UpstreamState",
    tool: dict[str, Any],
    arguments: dict[str, Any],
) -> float | None:
    properties = tool.get("inputSchema", {}).get("properties", {})
    timeout_schema = properties.get("timeout_seconds") if isinstance(properties, dict) else None
    if not isinstance(timeout_schema, dict):
        return None

    raw = arguments.get("timeout_seconds", timeout_schema.get("default"))
    if raw is None:
        return None

    try:
        requested = max(1.0, float(raw))
    except (TypeError, ValueError):
        return None

    base = float(state.service.get("timeout_seconds", 25))
    return min(
        max(base, requested + _LONG_CALL_TIMEOUT_MARGIN_SECONDS),
        _MAX_LONG_CALL_TIMEOUT_SECONDS,
    )


def _extract_json_response(response: httpx.Response) -> dict[str, Any]:
    ctype = response.headers.get("content-type", "").lower()
    if "application/json" in ctype:
        return response.json()
    text = response.text
    if "text/event-stream" in ctype or text.lstrip().startswith("event:") or "\ndata:" in text:
        payloads: list[str] = []
        for line in text.splitlines():
            if line.startswith("data:"):
                payloads.append(line[5:].strip())
        for payload in reversed(payloads):
            if payload and payload != "[DONE]":
                try:
                    return json.loads(payload)
                except json.JSONDecodeError:
                    continue
        raise ValueError("No JSON payload found in SSE response")
    return response.json()


@dataclass
class UpstreamState:
    service: dict[str, Any]
    session_id: str | None = None
    initialized: bool = False
    tools: list[dict[str, Any]] = field(default_factory=list)
    last_error: str = ""
    # Code-only catalog attempt outcome, exposed only on authenticated /router/status.
    # RESPONSE_RECEIVED is not catalog validation, data access or process health.
    profile_catalog_diagnostic: str = 'NOT_CHECKED'
    last_ok: float = 0.0
    init_lock: asyncio.Lock = field(default_factory=asyncio.Lock)


class MCPRegistry:
    def __init__(self) -> None:
        self.states: dict[str, UpstreamState] = {}
        self.tool_index: dict[str, tuple[str, str]] = {}
        self.clients: dict[str, httpx.AsyncClient] = {}
        self.reload_config()

    def reload_config(self) -> None:
        old = self.states
        self.states = {}
        for svc in load_services():
            prev = old.get(svc["id"])
            state = prev if prev else UpstreamState(service=svc)
            old_url = state.service.get("url") if prev else None
            state.service = svc
            if prev and old_url != svc.get("url"):
                state.session_id = None
                state.initialized = False
                state.tools = []
            self.states[svc["id"]] = state
        self.rebuild_index()

    def enabled_states(self) -> list[UpstreamState]:
        return [s for s in self.states.values() if s.service.get("enabled", True)]

    def get_mapping(self, public_name: str) -> tuple[str, str]:
        mapping = self.tool_index.get(public_name)
        if not mapping:
            raise KeyError(f"Unknown tool: {public_name}")
        return mapping

    def _client(self, state: UpstreamState) -> httpx.AsyncClient:
        sid = str(state.service["id"])
        client = self.clients.get(sid)
        if client is None:
            timeout = float(state.service.get("timeout_seconds", 25))
            limits = httpx.Limits(max_connections=32, max_keepalive_connections=16, keepalive_expiry=30.0)
            client = httpx.AsyncClient(timeout=timeout, trust_env=False, limits=limits)
            self.clients[sid] = client
        return client

    async def close(self) -> None:
        clients = list(self.clients.values())
        self.clients.clear()
        if clients:
            await asyncio.gather(*(c.aclose() for c in clients), return_exceptions=True)

    async def _post(
        self,
        state: UpstreamState,
        payload: dict[str, Any],
        *,
        timeout_seconds: float | None = None,
    ) -> dict[str, Any]:
        headers = {
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
            "User-Agent": "Zagent-Tunnel-Router/1.0.0",
            "X-Zagent-Internal-Token": internal_token(),
        }
        if state.session_id:
            headers["Mcp-Session-Id"] = state.session_id
        client = self._client(state)
        response = await client.post(
            state.service["url"],
            json=payload,
            headers=headers,
            timeout=timeout_seconds if timeout_seconds is not None else client.timeout,
        )
        if response.status_code == 404 and state.session_id and payload.get("method") != "tools/call":
            state.session_id = None
            state.initialized = False
            headers.pop("Mcp-Session-Id", None)
            response = await client.post(
                state.service["url"],
                json=payload,
                headers=headers,
                timeout=timeout_seconds if timeout_seconds is not None else client.timeout,
            )
        response.raise_for_status()
        sid = response.headers.get("mcp-session-id")
        if sid:
            state.session_id = sid
        if response.status_code == 202 or not response.content:
            return {}
        return _extract_json_response(response)

    async def ensure_initialized(self, state: UpstreamState) -> None:
        if state.initialized:
            return
        async with state.init_lock:
            if state.initialized:
                return
            req_id = uuid.uuid4().hex
            payload = {
                "jsonrpc": "2.0",
                "id": req_id,
                "method": "initialize",
                "params": {
                    "protocolVersion": MCP_PROTOCOL_VERSION,
                    "capabilities": {},
                    "clientInfo": CLIENT_INFO,
                },
            }
            try:
                result = await self._post(state, payload)
                if "error" in result:
                    raise RuntimeError(result["error"])
                await self._post(
                    state,
                    {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}},
                )
                state.initialized = True
                state.last_ok = time.time()
                state.last_error = ""
            except Exception as exc:
                state.initialized = False
                state.last_error = str(exc)
                raise

    async def refresh_service(self, service_id: str) -> dict[str, Any]:
        state = self.states[service_id]
        if not state.service.get("enabled", True):
            state.tools = []
            self.rebuild_index()
            return {"ok": False, "disabled": True, "tools": 0}
        try:
            await self.ensure_initialized(state)
            response = await self._post(
                state,
                {"jsonrpc": "2.0", "id": uuid.uuid4().hex, "method": "tools/list", "params": {}},
            )
            if "error" in response:
                raise RuntimeError(response["error"])
            state.tools = list(response.get("result", {}).get("tools", []))
            state.last_ok = time.time()
            state.last_error = ""
            self.rebuild_index()
            return {"ok": True, "tools": len(state.tools)}
        except Exception as exc:
            state.last_error = str(exc)
            state.initialized = False
            state.tools = []
            self.rebuild_index()
            return {"ok": False, "tools": 0, "error": str(exc)}

    async def restart_service(self, service_id: str) -> dict[str, Any]:
        state = self.states[service_id]
        state.session_id = None
        state.initialized = False
        state.tools = []
        self.rebuild_index()
        return await self.refresh_service(service_id)

    async def refresh_all(self) -> dict[str, Any]:
        states = self.enabled_states()
        results = await asyncio.gather(
            *(self.refresh_service(s.service["id"]) for s in states),
            return_exceptions=True,
        )
        out: dict[str, Any] = {}
        for state, result in zip(states, results):
            out[state.service["id"]] = (
                {"ok": False, "error": str(result), "tools": 0}
                if isinstance(result, Exception)
                else result
            )
        return out

    def rebuild_index(self) -> None:
        index: dict[str, tuple[str, str]] = {}
        for state in self.enabled_states():
            ns = state.service["namespace"]
            for tool in state.tools:
                upstream = str(tool.get("name", "")).strip()
                if not upstream:
                    continue
                public = public_tool_name(ns, upstream)
                if public == CATALOG_TOOL:
                    continue  # private authenticated adapter call only
                if public in PROFILE_ADMIN_SCOPES and state.service['id'] not in {'zagent_files', 'zagent_files_v3'}:
                    continue
                if public in index:
                    raise RuntimeError(f"Tool collision '{public}'")
                index[public] = (state.service["id"], upstream)
        self.tool_index = index

    def service_public_tools(self, service_id: str) -> list[dict[str, Any]]:
        state = self.states[service_id]
        ns = state.service["namespace"]
        return [
            {
                "name": public_tool_name(ns, str(tool.get("name", "")).strip()),
                "upstream_name": str(tool.get("name", "")).strip(),
                "description": str(tool.get("description", "")).strip(),
            }
            for tool in state.tools
            if str(tool.get("name", "")).strip()
        ]

    def list_public_tools(self) -> list[dict[str, Any]]:
        tools: list[dict[str, Any]] = []
        for state in self.enabled_states():
            ns = state.service["namespace"]
            for tool in state.tools:
                upstream = str(tool.get("name", "")).strip()
                if not upstream:
                    continue
                item = dict(tool)
                item["name"] = public_tool_name(ns, upstream)
                if item['name'] == CATALOG_TOOL:
                    continue
                if item['name'] in PROFILE_ADMIN_SCOPES and state.service['id'] not in {'zagent_files', 'zagent_files_v3'}:
                    continue
                desc = str(item.get("description", "")).strip()
                item["description"] = f"[{state.service['name']}] {desc}".strip()
                tools.append(item)
        return tools

    def status(self) -> dict[str, Any]:
        services = []
        for state in self.states.values():
            services.append({
                "id": state.service["id"],
                "name": state.service["name"],
                "namespace": state.service["namespace"],
                "url": state.service["url"],
                "permanent": state.service.get("permanent", False),
                "enabled": state.service.get("enabled", True),
                "initialized": state.initialized,
                "tools": len(state.tools),
                "last_ok": state.last_ok or None,
                "last_error": state.last_error or None,
                'profile_catalog_diagnostic': state.profile_catalog_diagnostic,
            })
        return {
            "ok": True,
            "service": "Zagent Tunnel1 Router Core",
            "version": "1.0.0",
            "upstream_tool_count": len(self.tool_index),
            "services": services,
        }

    async def profile_catalog_snapshot(self, context: dict[str, Any]) -> dict[str, Any]:
        candidates = [s for s in self.enabled_states() if s.service['id'] in {'zagent_files', 'zagent_files_v3'}]
        if len(candidates) != 1:
            raise AuthorizationError('PROFILE_CATALOG_NOT_CONFIGURED', 503)
        state = candidates[0]
        state.profile_catalog_diagnostic = 'REQUEST_STARTED'
        try:
            await self.ensure_initialized(state)
            response = await self._post(state, {'jsonrpc': '2.0', 'id': uuid.uuid4().hex,
                'method': 'tools/call', 'params': {'name': CATALOG_TOOL, 'arguments': {},
                    '_meta': {'zagent.profile_catalog_context': context}}})
            if not isinstance(response, dict):
                raise ValueError('INVALID_RESPONSE')
            if 'error' in response:
                state.profile_catalog_diagnostic = 'RPC_ERROR'
                raise AuthorizationError('PROFILE_CATALOG_UNAVAILABLE', 503)
            result = response.get('result')
            if not isinstance(result, dict):
                raise ValueError('INVALID_RESPONSE')
            if result.get('isError') is True or result.get('ok') is False:
                state.profile_catalog_diagnostic = 'DOMAIN_ERROR'
                raise AuthorizationError('PROFILE_CATALOG_UNAVAILABLE', 503)
            if isinstance(result.get('structuredContent'), dict):
                result = result['structuredContent']
            else:
                content = result.get('content')
                if isinstance(content, list) and len(content) == 1 and content[0].get('type') == 'text':
                    result = json.loads(content[0]['text'])
            if not isinstance(result, dict):
                raise ValueError('INVALID_RESPONSE')
            state.profile_catalog_diagnostic = 'RESPONSE_RECEIVED'
            return result  # Caller still validates catalog shape and current authority.
        except httpx.HTTPStatusError as exc:
            state.profile_catalog_diagnostic = ('PRIVATE_CHANNEL_REJECTED'
                if exc.response.status_code in (401, 403) else 'HTTP_FAILURE')
            raise AuthorizationError('PROFILE_CATALOG_UNAVAILABLE', 503) from None
        except httpx.RequestError:
            state.profile_catalog_diagnostic = 'TRANSPORT_UNAVAILABLE'
            raise AuthorizationError('PROFILE_CATALOG_UNAVAILABLE', 503) from None
        except AuthorizationError:
            # Preserve internal credential/placement denials and stable status codes.
            if state.profile_catalog_diagnostic == 'REQUEST_STARTED':
                state.profile_catalog_diagnostic = 'LOCAL_AUTHORIZATION_DENIED'
            raise
        except (ValueError, TypeError, AttributeError, KeyError):
            state.profile_catalog_diagnostic = 'INVALID_RESPONSE'
            raise AuthorizationError('PROFILE_CATALOG_UNAVAILABLE', 503) from None
        except RuntimeError:
            # initialize may return a private JSON-RPC error; never forward its text.
            state.profile_catalog_diagnostic = 'RPC_ERROR'
            raise AuthorizationError('PROFILE_CATALOG_UNAVAILABLE', 503) from None

    async def invoke(self, service_id: str, upstream_name: str, arguments: dict[str, Any], ctx: ExecContext) -> dict[str, Any]:
        state = self.states[service_id]
        await self.ensure_initialized(state)
        started = time.time()

        call_arguments = dict(arguments or {})
        selected_files_profile = None
        envelope = {}
        admin = ctx.execution_context.get('public_tool') in PROFILE_ADMIN_SCOPES
        if admin:
            if service_id not in {'zagent_files', 'zagent_files_v3'} or upstream_name != ctx.execution_context['public_tool']:
                raise AuthorizationError('PROFILE_ADMIN_MAPPING_INVALID', 403)
            envelope = ctx.execution_context['profile_admin_context']
            if envelope['payload_digest'] != digest(call_arguments):
                raise AuthorizationError('PROFILE_ADMIN_PAYLOAD_CHANGED', 403)
        elif service_id in {'zagent_files', 'zagent_files_v3'}:
            call_arguments = forward_files_arguments(ctx.execution_context['public_tool'],
                                                     call_arguments, ctx.execution_context)
            selected_files_profile = ctx.execution_context['effective_resources'][0]['profile_id']
        tool = next((item for item in state.tools if item.get("name") == upstream_name), {})
        properties = tool.get("inputSchema", {}).get("properties", {})
        capability = tool.get("_meta", {}).get("zagent.capability")
        # Files authority travels only in authenticated params._meta. Legacy
        # argument enrichment changes the payload bound by the consumer verifier.
        if "metadata" in properties and capability and service_id not in {"zagent_files", "zagent_files_v3"}:
            forwarded = {}
            forwarded.update({
                "session_id": ctx.session_id,
                "request_id": ctx.request_id,
                "task_id": ctx.task_id,
                "trace_id": ctx.trace_id,
                "idempotency_key": ctx.idempotency_key,
                "resource_key": ctx.resource_key,
                "access_mode": ctx.access_mode,
                "priority": ctx.priority,
                "device_id": _DEVICE_ID or None,
                "executed_on": _DEVICE_ID or None,
                "execution_context": dict(ctx.execution_context),
            })
            if ctx.profile_id and not forwarded.get("profile_id"):
                forwarded["profile_id"] = ctx.profile_id
            if not forwarded.get("profile_id"):
                inferred_profile = (
                    call_arguments.get("profile")
                    or call_arguments.get("source_profile")
                    or call_arguments.get("destination_profile")
                )
                if inferred_profile:
                    forwarded["profile_id"] = str(inferred_profile)
            call_arguments["metadata"] = forwarded

        call_timeout = _tool_call_timeout_seconds(state, tool, call_arguments)
        response = await self._post(
            state,
            {
                "jsonrpc": "2.0",
                "id": ctx.request_id or uuid.uuid4().hex,
                "method": "tools/call",
                "params": {"name": upstream_name, "arguments": call_arguments, "_meta":
                    {'zagent.profile_admin_context': dict(envelope)} if admin else {
                    "zagent.session_id": ctx.session_id, "zagent.request_id": ctx.request_id,
                    "zagent.trace_id": ctx.trace_id, "zagent.task_id": ctx.task_id,
                    "zagent.device_id": _DEVICE_ID or None,
                    "zagent.execution_context": dict(ctx.execution_context)}},
            },
            timeout_seconds=call_timeout,
        )
        if "error" in response:
            raise RuntimeError(response["error"])
        state.last_ok = time.time()
        state.last_error = ""
        result = response.get("result", {})
        if isinstance(result, dict):
            meta = dict(result.get("_meta") or {})
            meta.update({
                "zagent.trace_id": ctx.trace_id,
                "zagent.session_id": ctx.session_id,
                "zagent.profile_id": selected_files_profile or ctx.profile_id or None,
                "zagent.request_id": ctx.request_id,
                "zagent.task_id": ctx.task_id,
                "zagent.service_id": service_id,
                "zagent.device_id": _DEVICE_ID or None,
                "zagent.executed_on": _DEVICE_ID or None,
                "zagent.agent_ms": round((time.time() - started) * 1000, 3),
            })
            result = dict(result)
            result["_meta"] = meta
        return result
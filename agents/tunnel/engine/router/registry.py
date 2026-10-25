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
            })
        return {
            "ok": True,
            "service": "Zagent Tunnel1 Router Core",
            "version": "1.0.0",
            "upstream_tool_count": len(self.tool_index),
            "services": services,
        }

    async def invoke(self, service_id: str, upstream_name: str, arguments: dict[str, Any], ctx: ExecContext) -> dict[str, Any]:
        state = self.states[service_id]
        await self.ensure_initialized(state)
        started = time.time()

        call_arguments = dict(arguments or {})
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
                "params": {"name": upstream_name, "arguments": call_arguments, "_meta": {
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
                "zagent.profile_id": ctx.profile_id or None,
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
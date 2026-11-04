"""Local MCP HTTP acceptance for the bundled QGIS agent, read-only QGIS calls.

Runs an isolated QGIS MCP process on loopback and terminates it in finally.
Does not modify user QGIS projects, Production services, Core, or the plugin.
"""
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time

import httpx

ROOT = Path(__file__).resolve().parents[1]
AGENT = ROOT / "agents" / "qgis"
PYTHON = AGENT / "runtime" / "python" / "python.exe"
ENGINE = AGENT / "engine"
PORT = 19150
URL = f"http://127.0.0.1:{PORT}/mcp"


def decode(response):
    response.raise_for_status()
    ctype = response.headers.get("content-type", "")
    if "text/event-stream" in ctype:
        records = [line[5:].strip() for line in response.text.splitlines() if line.startswith("data:")]
        if not records:
            raise AssertionError("MCP SSE yielded no JSON data event")
        return json.loads(records[-1])
    return response.json()


def main():
    with socket.socket() as probe:
        probe.settimeout(0.4)
        if probe.connect_ex(("127.0.0.1", PORT)) == 0:
            raise AssertionError("QGIS MCP port 19150 is occupied; no process started")

    env = dict(os.environ)
    for key in ("VIRTUAL_ENV", "PYTHONHOME", "PYTHONPATH"):
        env.pop(key, None)
    env.update({
        "QGIS_MCP_TRANSPORT": "streamable-http",
        "ZAGENT_QGIS_BIND_HOST": "127.0.0.1",
        "ZAGENT_QGIS_BIND_PORT": str(PORT),
        "QGIS_MCP_HOST": "127.0.0.1",
        "QGIS_MCP_PORT": "9876",
        "QGIS_MCP_LOG_FILE": "",
        "PYTHONDONTWRITEBYTECODE": "1",
    })
    proc = subprocess.Popen(
        [str(PYTHON), "-m", "zagent_qgis.launch"],
        cwd=str(ENGINE),
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    try:
        with httpx.Client(trust_env=False, timeout=6) as client:
            deadline = time.monotonic() + 16
            while True:
                if proc.poll() is not None:
                    raise AssertionError(f"QGIS MCP process exited with {proc.returncode}")
                try:
                    with socket.create_connection(("127.0.0.1", PORT), timeout=0.5):
                        break
                except OSError:
                    if time.monotonic() > deadline:
                        raise AssertionError("QGIS MCP did not listen on 19150")
                    time.sleep(0.2)
            headers = {"Accept": "application/json, text/event-stream",
                       "Content-Type": "application/json",
                       "MCP-Protocol-Version": "2025-06-18"}
            response = client.post(URL, headers=headers, json={
                "jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
                    "protocolVersion": "2025-06-18", "capabilities": {},
                    "clientInfo": {"name": "Zagent-QGIS-smoke", "version": "1.0"}
                }
            })
            result = decode(response)
            assert "serverInfo" in result.get("result", {}), result
            session = response.headers.get("mcp-session-id")
            if session:
                headers["Mcp-Session-Id"] = session
            response = client.post(URL, headers=headers,
                json={"jsonrpc": "2.0", "method": "notifications/initialized"})
            assert response.status_code in (200, 202), response.status_code

            tools = []
            cursor = None
            for page in range(10):
                params = {"cursor": cursor} if cursor else {}
                data = decode(client.post(URL, headers=headers, json={
                    "jsonrpc": "2.0", "id": 100 + page,
                    "method": "tools/list", "params": params
                }))["result"]
                tools.extend(data.get("tools", []))
                cursor = data.get("nextCursor")
                if not cursor:
                    break
            names = [item["name"] for item in tools]
            if len(names) != len(set(names)):
                raise AssertionError("Duplicate QGIS MCP tools")
            assert len(tools) == 125, f"Unexpected QGIS catalog size: {len(tools)}"
            assert "ping" in names and "execute_code" in names
            print("QGIS_MCP_HTTP_INITIALIZE_PASS")
            print("QGIS_MCP_HTTP_TOOL_COUNT", len(tools))

            reply = decode(client.post(URL, headers=headers, json={
                "jsonrpc": "2.0", "id": 300, "method": "tools/call",
                "params": {"name": "ping", "arguments": {}}
            }))
            answer = reply.get("result", {})
            structured = answer.get("structuredContent", {})
            content = answer.get("content") or []
            if not structured and content and content[0].get("type") == "text":
                try:
                    structured = json.loads(content[0]["text"])
                except (ValueError, TypeError):
                    structured = {}
            assert "pong" in json.dumps(structured).lower(), f"QGIS ping did not return pong: {str(answer)[:200]}"
            print("QGIS_MCP_HTTP_PING_PASS")
            if session:
                try:
                    client.delete(URL, headers=headers)
                except httpx.HTTPError:
                    pass
    finally:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=6)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=6)
        print("QGIS_SMOKE_PROCESS_CLEANED_UP", proc.poll() is not None)


if __name__ == "__main__":
    main()
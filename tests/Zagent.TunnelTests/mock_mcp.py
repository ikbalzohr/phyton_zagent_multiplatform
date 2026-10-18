from __future__ import annotations

import argparse
import asyncio
import json
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response
import uvicorn

app = FastAPI(title="Zagent Tunnel Mock MCP")


@app.get("/healthz")
async def healthz():
    return {"ok": True}


@app.post("/mcp")
async def mcp(request: Request):
    body = await request.json()
    req_id = body.get("id")
    method = body.get("method")
    params = body.get("params") or {}

    if method == "initialize":
        return JSONResponse({
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "protocolVersion": params.get("protocolVersion", "2025-06-18"),
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "Mock MCP", "version": "1.0"}
            }
        })

    if method == "notifications/initialized":
        return Response(status_code=202)

    if method == "tools/list":
        return JSONResponse({
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "tools": [
                    {
                        "name": "ping",
                        "description": "Echo a value.",
                        "inputSchema": {
                            "type": "object",
                            "properties": {
                                "value": {"type": "string"}
                            },
                            "required": ["value"],
                            "additionalProperties": False
                        }
                    },
                    {
                        "name": "sleep",
                        "description": "Sleep for a requested duration.",
                        "inputSchema": {
                            "type": "object",
                            "properties": {
                                "delay_ms": {
                                    "type": "integer",
                                    "minimum": 1,
                                    "maximum": 10000
                                },
                                "timeout_seconds": {
                                    "type": "integer",
                                    "minimum": 1,
                                    "maximum": 30,
                                    "default": 5
                                }
                            },
                            "required": ["delay_ms"],
                            "additionalProperties": False
                        }
                    }
                ]
            }
        })

    if method == "tools/call":
        name = params.get("name")
        arguments = params.get("arguments") or {}

        if name == "ping":
            value = str(arguments.get("value", ""))
            return JSONResponse({
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "content": [
                        {
                            "type": "text",
                            "text": json.dumps({"echo": value})
                        }
                    ]
                }
            })

        if name == "sleep":
            delay_ms = int(arguments.get("delay_ms", 1))
            await asyncio.sleep(delay_ms / 1000)
            return JSONResponse({
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "content": [
                        {
                            "type": "text",
                            "text": json.dumps({
                                "slept_ms": delay_ms
                            })
                        }
                    ]
                }
            })

        return JSONResponse({
            "jsonrpc": "2.0",
            "id": req_id,
            "error": {"code": -32601, "message": f"Unknown tool: {name}"}
        })

    return JSONResponse({
        "jsonrpc": "2.0",
        "id": req_id,
        "error": {"code": -32601, "message": f"Unknown method: {method}"}
    })


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, required=True)
    args = parser.parse_args()
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()

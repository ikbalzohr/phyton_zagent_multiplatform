# Architecture

ChatGPT / MCP Client
        |
Secure MCP Tunnel
        |
MCP Streamable HTTP (Python 3.11)
        |
request-id file IPC
        |
Persistent in-process Bridge (Python 2.7)
        |
arcpy.mapping.MapDocument("CURRENT")
        |
ArcMap 10.6.1

## Why split Python runtimes?

ArcMap 10.6.1 depends on Python 2.7/ArcPy. Modern MCP tooling requires a modern Python runtime. IPC keeps the two environments isolated and maintainable.

## IPC

- `ipc/inbox/<request_id>.json`
- `ipc/outbox/<request_id>.json`
- processed commands → `ipc/archive/`
- bridge errors → `ipc/logs/bridge_errors.log`

This avoids the old single `command.json/result.json` bottleneck and supports clean request correlation.

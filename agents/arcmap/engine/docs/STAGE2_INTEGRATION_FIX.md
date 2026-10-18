# Stage 2 explicit integration fix

## Root cause

The live ArcMap bridge registers actions in `arcmap_bridge/core/registry.py`, loaded by `core/dispatcher.py`. The prior Stage 2 hook ran from `ArcMapAgent.pyt` and searched the toolbox module globals for an action registry dict, so it could not reliably reach the real registry.

The MCP server uses `mcp.server.MCPServer` and a deterministic `module.register(mcp, services)` pattern. The prior Stage 2 auto-installer searched for a generic transport callable/FastMCP object in `server.py` globals. That did not match the actual architecture.

## Correct integration

- Bridge: `core/dispatcher.py` imports `stage2.bridge.install_into_registry` and installs exactly 8 Stage 2 actions into the real `ACTIONS` registry.
- MCP: `mcp_server/tools/stage2.py` defines exactly 8 normal MCP tools and `mcp_server/server.py` registers the module like every other tool module.

Expected totals:

- Existing bridge: 90
- Stage 2 bridge: 8
- Total bridge: 98
- Existing MCP: 91
- Stage 2 MCP: 8
- Total MCP: 99

## Production defaults

Stage 2 defaults to PDF + PNG only, 400 DPI, output folder `Hasil Peta`, and naming `PETA A4 <company_name> - <map_type>`.

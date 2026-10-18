# Integration Checklist — ArcMap 10.6.1

This package is designed for:

- immutable baseline: `<optional legacy immutable baseline>`
- active development: `<Zagent ArcMap engine>`

## 1. Install safely

1. Close any old Zagent MCP/bridge process.
2. Back up the existing `Work` folder if it contains local-only changes.
3. Extract/copy this package so `<Zagent ArcMap engine>\arcmap_bridge` exists directly.
4. Do **not** copy, move, rename, or overwrite anything inside `Manual`.
5. Run `Work\scripts\validate_work.cmd`. Continue only when `RESULT: PASS` is shown.

## 2. Start ArcMap bridge

With the target MXD already open in ArcMap 10.6.1, use one of these methods:

- Add `Work\arcmap_bridge\ArcMapAgent.pyt` to ArcMap and run **Start Live Bridge**; or
- paste the contents of `Work\scripts\arcmap_start_in_python_window.txt` into ArcMap's Python Window.

Expected message: `ZAGENT ARCMAP LIVE BRIDGE STARTED`.

## 3. Start modern MCP side

One-time only: run `Work\scripts\install_mcp_env.cmd`.

For each session:

1. run `Work\scripts\start_mcp_http.cmd`;
2. ensure the tunnel environment variables are loaded;
3. run `Work\scripts\start_tunnel.cmd`.

The HTTP preflight must report `STATUS: READY` before the tunnel is started.

## 4. Safe validation order

Use read-only checks first:

1. `arcmap_ping`
2. `arcmap_get_status`
3. `arcmap_list_layers`
4. `arcmap_list_layout_text`
5. `arcmap_inspect_current_map`

Then test one reversible live edit without saving the MXD, for example title or layer visibility. `allow_save`, destructive operations, and geoprocessing remain disabled by default.

## 5. Expected expanded tool surface

After the updated MCP server is connected, the tool list should expand from the old 8-tool baseline to **33 tools** to include inspection, layer/data management, layout positioning/scale, labels, symbology, selection, geoprocessing, export, and explicit save controls documented in `docs\TOOL_CATALOG.md`.

## 6. Safety guarantees added in 0.1.1

- persistent writes resolving inside `Manual` are blocked;
- `Near` requires destructive permission because it mutates the input dataset;
- Python 3 `__pycache__`/`.pyc` files are excluded from the ArcMap Python 2.7 bridge package;
- static validation checks MCP-to-bridge action parity before integration.

## 7. Refresh ChatGPT tool discovery

The existing custom MCP app may keep the old 8-tool schema for an already-open chat. After the new MCP server and tunnel are running, refresh/reconnect the custom app or open a new chat so ChatGPT discovers the full 33-tool surface.

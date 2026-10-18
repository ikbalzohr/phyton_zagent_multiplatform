# ArcMap Native Layer Properties, Existing Grids, Vision Orientation — Dev Code Checkpoint
Tanggal: 2026-10-08
Status: SOURCE CHANGED — NOT TESTED / NOT BUILT / NOT DEPLOYED
Target: D:\3-Ikbalzohr\Agent\appBridge\production\Zagent\v3 (development source tree).
Runtime installed: D:\3-Ikbalzohr\Agent\ZohrSystem\Zagent — intentionally untouched.

## Changes
1. arcmap_bridge/features/native_layer_properties.py:
   - Read Layer Properties with an explicit capability matrix.
   - Native ArcObjects IGeoFeatureLayer + IUniqueValueRenderer creation, even from OTHER/SIMPLE renderer.
   - Scan data for unique categories, single value field, other-values toggle, label and symbol overrides, refresh, remove category, serializable read-back.
   - Session-scoped .lyr snapshot only as recovery input, not a renderer template; automatic rollback on failed native renderer change.
   - Safe ArcPy setters for name, visible, definition query, transparency, min/max scale and showLabels.
   - Unsupported advanced property tabs (joins, HTML popup, Maplex placement and schema/field alias write) are reported as unsupported rather than simulated.

2. arcmap_bridge/features/native_grids.py:
   - Inspect existing IMapGrids/IMapGrid/IGraticule/IMeasuredGrid without opening dialogs or switching ArcMap view.
   - Change grid in place by explicit name/index: X/Y intervals (30 arcseconds = 1/120 degree), name, visibility, line symbol, ticks, subticks, label sides and label offset.
   - Session-scoped snapshot/restore; explicitly guarded create and remove; no implicit MXD save.
   - Some driver/version-specific label DMS formatting and map grid border editing remain pending native API verification. Unreadable properties return null/explicit limitation.

3. mcp_server/window_capture.py:
   - Removes an unconditional vertical row flip that inverted the captured ArcMap window on affected GDI bitmap drivers.
   - PNG always emitted top-down; capture's source bitmap row-order default is now top-down.
   - Compatibility switch: ZAGENT_ARCMAP_CAPTURE_ROW_ORDER=bottom-up, only for drivers needing legacy orientation.
   - Capture metadata records source/png row order for diagnostics.

4. MCP surface + dispatcher:
   - Import two new Python 2.7-compatible bridge feature modules into core/dispatcher.py.
   - Register two MCP tool modules in mcp_server/server.py, adding 12 tools beyond the existing 132; projected 144 tool surface after fresh Dev process registration, NOT RUNTIME VERIFIED.
   - New calls use AgentServices.call with live_write guards, CURRENT-MXD ownership and post-action verification.
   - Existing stage2/stage3/tools are retained; production installed runtime and Files service remain unchanged.

## Deferred verification (DO NOT RUN until explicitly ordered)
- Python 2.7 syntax/import checks, Python 3 MCP syntax checks and tool registry count.
- Unit/integration/regression suites and build/bundle.
- ArcMap 10.6.1 live test: polygon KELAS = PIPPIB PRIMER / NON-PIPPIB, OTHER -> UNIQUE_VALUES, show_other_values false, per-category symbols, screenshot and no-save read-back.
- Existing graticule 1 minute -> 30 seconds X/Y; no duplicate, same COM object, original MXD unsaved, snapshot restore.
- Label/tick/line/border capabilities per installed ArcObjects COM type library.
- Vision screenshot orientation: PrintWindow and BitBltFallback; different DPI settings and monitors; ensure no rotation or vertical flip.
- Check StyleSnapshot rollback, grid restore after create/remove, default Dev upstream read-only safety, Tool Registry count, and 16-step regression.

## Operator constraints
- No tests, build, runtime reload, restart, bundling, installer or production promotion in this change.
- No live ArcMap mutation or MXD save during implementation.
- All new behavior is a source candidate until explicit acceptance.
- The plan's advanced/full Layer Properties coverage is staged and not yet complete.

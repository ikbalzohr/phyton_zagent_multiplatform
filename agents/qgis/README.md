# Zagent QGIS Agent (bundled upstream v0.15.2)

This is the **fifth managed service / optional extension** within Zagent
Multi Platform. The existing Files, Web, ArcMap and Tunnel services are
unchanged.

## Runtime architecture

ChatGPT/Claude/Hermes -> HTTPS OAuth Router -> **Zagent Core** controls the
`qgis.mcp` process -> HTTP MCP at `127.0.0.1:19150/mcp`
-> TCP bridge at `127.0.0.1:9876` -> user-owned **QGIS Desktop** plugin.

- Core registers `qgis.service`, starts/stops/restarts *only* the HTTP MCP
  process, marks its readiness by MCP initialize, and exposes the upstream to
  the Router as `zagent_qgis` with namespace `qgis`.
- The QGIS Desktop application and plugin are never started, killed, or
  silently replaced by Core. An absent QGIS Desktop plugin does not mean the
  HTTP MCP server failed to start: `qgis_ping` or `qgis_diagnose` confirms it.
- The existing Router QGIS passthrough requires the authenticated owner
  `files:read`, `files:write` and `files:execute` authority plus the
  approved Files resource and `files_powershell_run` tool permission.
  QGIS `execute_code` can execute owner-account Python inside QGIS; user
  confirmation and scope policies must remain enforced.
- A new ChatGPT MCP server/plugin is **not** needed: the same Router publishes
  `qgis_*` names dynamically. Expected additional 125 tools in granular mode.
- The upstream implementation is vendored without modifications at
  `engine/src/qgis_mcp`; the corresponding original QGIS plugin source is
  `engine/qgis_mcp_plugin`. Zagent's one-module adapter is
  `engine/src/zagent_qgis/launch.py`.

## Why the launcher adapter exists

QGIS MCP v0.15.2 with pinned `mcp` v1.26.0 creates FastMCP with a hard-coded
constructor port 8000, overriding the environment's `FASTMCP_PORT`.
`zagent_qgis.launch` sets the FastMCP settings explicitly to loopback:19150
and calls its existing `mcp.run(transport="streamable-http")`. It does not
fork or rewrite any upstream QGIS tools.

## Python runtime provisioning

QGIS MCP requires Python **>= 3.12** and is independent from the 3.11
runtimes used by Files, Tunnel and ArcMap. The generated directory
`agents/qgis/runtime/python` is ignored by Git; it must be provisioned
before packaging. From the source root, using an approved Python 3.12
distribution and its preinstalled locked dependencies:

```powershell
./packaging/scripts/Prepare-QgisRuntime.ps1 `
  -PythonHome "<Python-3.12-home>" `
  -SitePackages "<QGIS-MCP-venv>/Lib/site-packages" `
  -OutputRoot "./agents/qgis/runtime/python" `
  -QgisEngine "./agents/qgis/engine"
```

The provisioner refuses overwrites, removes upstream editable `.pth` paths
and checks imports using a relocated runtime. It **does not** install packages
on a customer's machine or download dependencies at Core startup. The
release payload builder copies this self-contained runtime into
`agents/qgis/runtime/python` of the installation.

## QGIS Desktop plugin

An installed, version-compatible `QGIS MCP` desktop plugin is required
for actual GIS operations. QGIS 3.44.2 with plugin 0.15.2 was present on
the developer host, listening at `127.0.0.1:9876` and `ping` PASS.
The vendored plugin source is provided for licensed redistribution and
explicit user-admin installation, but is **not** silently installed into
the user's QGIS profile. Do not overwrite a running QGIS plugin.

## Source tests

- `dotnet run --project tests/Zagent.QgisTests/Zagent.QgisTests.csproj`
- `agents/qgis/runtime/python/python.exe tests/qgis_runtime_smoke.py`
  (uses loopback 19150, read-only MCP initialize/list/ping, stops test process)
- `py -3.11 -m unittest discover -s tests -p test_*.py -q` from
  `agents/tunnel/engine`
- `dotnet run --project tests/Zagent.ManagerTests` and ArchitectureTests

The regular product release gates and the live installed Core/Router OAuth
catalog need separate acceptance. This source integration does **not**
automatically deploy or restart the currently running Multi Platform.

## Third-party licensing and provenance

Source: Nicolas Karasiak, nkarasiak/qgis-mcp, version 0.15.2.
The upstream project and QGIS plugin use **GPL-2.0-or-later**. Original
`engine/LICENSE`, `engine/src/qgis_mcp/LICENSE`, and
`engine/qgis_mcp_plugin/LICENSE` are preserved together with source and
attribution. `UPSTREAM-SNAPSHOT.json` records the source commit.
Python and other dependencies retain their own licenses. Review the GPL
source-availability/distribution obligations before commercial release.
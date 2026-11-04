# QGIS MCP integrated as a Zagent Multi Platform agent — 4 Nov 2026

## Goal and boundaries

User requested integrating the already cloned
`D:\3-Ikbalzohr\Agent\qgis-mcp` into the independent product source at
`D:\3-Ikbalzohr\Agent\phyton_zagent_multiplatform\agents`,
as an additional Core-managed agent rather than an unrelated external MCP
service. Work is **source integration only**; no live Core restart, release
installation, Cloudflare/Keycloak changes, ChatGPT plugin reset, or Zagent
Production changes.

## Audited upstream

- `nkarasiak/qgis-mcp` 0.15.2, original Git commit recorded in
  `agents/qgis/UPSTREAM-SNAPSHOT.json`; upstream clone Git status clean.
- 43 Git-tracked upstream files copied with matching SHA256 to
  `agents/qgis/engine`. Included original GPL-2.0-or-later license, Python
  server source `src/qgis_mcp`, QGIS plugin source `qgis_mcp_plugin`,
  `pyproject.toml`, `uv.lock` and upstream README.
- Plugin QGIS 0.15.2 was already installed in the user's QGIS 3.44.2 profile,
  and QGIS Desktop was running with local listener 127.0.0.1:9876.
  *Some installed plugin file hashes differ from the clone source despite the
  same 0.15.2 metadata; the existing plugin was not overwritten.*
- Upstream Python >=3.12, HTTP MCP when `streamable-http` is selected,
  desktop bridge uses length-framed TCP on 9876. Runtime interface offers 125
  tools in granular mode.

## Implemented source changes

1. Added `agents/qgis/engine`, `qgis.component.json`, and provenance,
   documentation and Git runtime exclusion.
2. Created `packaging/scripts/Prepare-QgisRuntime.ps1` to copy an approved
   Python3.12 donor and its dependency site-packages into a **portable,
   relocation-tested** private agent runtime, refusing overwrites and
   removing the source clone's editable absolute path.
3. Implemented a small Zagent-owned Python module
   `engine/src/zagent_qgis/launch.py`. Upstream FastMCP constructor defaults
   override the `FASTMCP_PORT` variable (found through failed HTTP smoke).
   Adapter assigns the intended loopback host and TCP port before starting
   upstream `mcp.run`. Upstream source was not modified.
4. Updated `QgisIntegration.Resolve` to automatically choose bundled
   `agents/qgis/runtime/python/python.exe` and bundled engine when present.
   An incomplete/missing optional bundle does not stop Core startup.
   The managed process now uses `-m zagent_qgis.launch`, protected
   loopback bind 127.0.0.1:19150, external QGIS TCP bridge
   127.0.0.1:9876. Core owns *only* the HTTP MCP process, never QGIS Desktop.
   Registration remains a Core supervisor/controller with independent
   lifecycle and startup before Tunnel discovery.
5. Registered QGIS in `component-manifest.json` as an additional product
   component. Updated `Build-ProductionPayload.ps1` to bundle QGIS
   server/plugin source, license/provenance, and isolated Python runtime.
   The upstream QGIS dependencies are not rebuilt or downloaded at runtime.
6. Removed the obsolete, duplicate default QGIS service at port 8000 from
   `agents/tunnel/engine/config/additional_services.json`. Built-in QGIS
   registration already provides `zagent_qgis` to the Router, so retaining
   the old additional service would cause catalog/service-ID collisions.
7. Added QGIS namespace-to-agent mapping to `RouterManagerService` and
   `TunnelManagerReadModel`, and ordered `qgis.service` after ArcMap for
   Core manager/dashboard agent listings.
8. Added executable cross-process acceptance
   `tests/qgis_runtime_smoke.py` and extended Qgis .NET tests for bundled
   auto-discovery, incomplete payload behavior and managed launcher.

## Validation performed

| Test | Result |
|---|---|
| Upstream 43 files copied with SHA256 equality | PASS |
| Portable Python3.12 import from separate runtime | PASS |
| MCP tool registry | PASS — 125 |
| QGIS Desktop socket direct ping | PASS — pong=true |
| Actual managed MCP HTTP initialize + tools/list | PASS — 125 |
| Actual MCP `tools/call ping` to live QGIS Desktop | PASS |
| Ephemeral MCP process cleanup | PASS |
| Portable relocation into another directory + GPL license | PASS |
| `Zagent.QgisTests` | PASS |
| Core .NET Debug build | PASS — 0 warnings/0 errors |
| `Zagent.ArchitectureTests` | 29/29 PASS |
| `Zagent.ManagerTests` | 19/19 PASS |
| Router Python unittest suite | 173, 3 skipped, PASS |
| PowerShell packaging script syntax | PASS |
| Source duplicate-registration/default config check | PASS |
| Full upstream pytest unit suite | NOT RUN — runtime intentionally excludes pytest |
| Official complete release payload build | NOT RUN — existing unrelated release gates and runtime bundle prerequisites |
| Live installed Core QGIS lifecycle + ChatGPT `qgis_*` discovery | NOT RUN — installed Core not changed/restarted |

No source Git commit/push, Setup installation, OAuth changes or endpoint
migration occurred.

## To activate on the installed Multi Platform

1. Use the tested full product installer workflow to publish the new Core
   binary and bundled `agents/qgis` payload with manifest hash and rollback.
   Installed Core must actually be updated to pick up bundled auto-discovery.
2. Preserve `data/`, OAuth grants, workspace profile, logs, process state and
   existing installed Files/Web/ArcMap/Tunnel; never modify Zagent Master.
3. Start/restart only the Multi Platform Core in the **owner-controlled
   maintenance window**. Core's agent startup order is
   Files → Web → ArcMap → QGIS → Router; lack of QGIS Desktop readiness must
   not block Router. Confirm `127.0.0.1:19150/mcp` listens and `qgis_ping`
   gives `pong=true` with QGIS Desktop plugin started.
4. Confirm `zagent_capabilities` / `tools/list` contains the discovered
   `qgis_*` tools (expected ~125 more than the prior 374; actual counts
   depend on upstream availability and client limits). For public QGIS tool
   access reuse existing owner Files read/write/execute authority and approved
   resource; do not create a second public MCP/Keycloak realm.
5. Validate a safe read-only GIS operation and one explicitly authorized
   mutating operation with appropriate user approvals, task receipts and
   result readbacks.

**Security/legal:** QGIS `execute_code` can run arbitrary Python using the
interactive Desktop user's authority. Loopback binding is necessary but not
equivalent to a sandbox. Retain existing OAuth and explicit Files command
authority. GPL-2.0-or-later upstream source and original licenses are bundled;
review applicable redistribution obligations before public release.
## Deployment follow-up — 4 Nov 2026

QGIS MCP source, isolated Python3.12 runtime and new Core Release binary
have been **installed directly** into the existing Multi Platform install
without a new rollback backup. Installed Setup verify 12,001/12,001
files PASS; installed QGIS HTTP initialize/list (125)/ping PASS.
**Core Launcher not started**: existing Production Files command allowlist
denied the executable, and no bypass/Production change was attempted.
Dashboard fifth-agent and live ChatGPT tools/list **NOT VERIFIED**.
Commit/push explicitly deferred pending user condition that all tests PASS.
See `docs/QGIS_ACTIVE_INSTALL_20261104.md`.
## Final live verification — PASS, 4 Nov 2026

Owner launched the installed Multi Platform; Dashboard shows
`qgis.service` Ready/Running as fifth agent, while the pre-existing
ArcMap Degraded warning remains separately documented. Live authenticated
ChatGPT MCP catalog returned **499 tools**, including **125 QGIS tools**.
`qgis_ping` completed successfully with `pong=true` using task receipt
and result retrieval. Final Core/Manager/Architecture/Router regression
PASS. See `QGIS_ACTIVE_INSTALL_20261104.md` for complete acceptance.
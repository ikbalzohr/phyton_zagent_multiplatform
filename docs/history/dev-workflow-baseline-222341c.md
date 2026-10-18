# Zagent DEV Workflow

Status: active development workflow. Do not bundle for routine debugging.

## Goal

Use the live source tree as the primary development system:

ChatGPT -> Zagent Dev Plugin -> Zagent DEV Tunnel -> Files / Web / ArcMap / Development Agents

Bundle/installer work resumes only after live plugin routing and feature validation pass.

## Start / Stop / Status

- Start: `dev\Start-Zagent-Dev.ps1`
- Start without rebuild: `dev\Start-Zagent-Dev.ps1 -NoBuild`
- Stop: `dev\Stop-Zagent-Dev.ps1`
- Status: `dev\Status-Zagent-Dev.ps1`

## DEV isolation

- Environment: `DEVELOPMENT`
- Manager pipe: `Zagent.Manager.Development`
- Supervisor lease: `Local\Zagent.v2.Supervisor.Development`
- Bind host: `127.0.0.3`
- Tunnel MCP: `19010`
- Tunnel health: `19011`
- Files MCP: `19020`
- Web MCP: `19030`
- ArcMap MCP: `19040`
- Development Agent Gateway range remains reserved: `18900-18999`
- Mutable data: `dev\data`
- Runtime overlays: `dev\runtime`

The installed/reference RC2 under `D:\3-Ikbalzohr\Agent\ZohrSystem\Zagent` remains separate.

## Zagent Dev Plugin

The dedicated Zagent Dev Plugin should use a separate Tunnel ID and API key.

When the Dev Plugin credentials are ready:

1. Start Zagent DEV.
2. Open Manager Settings.
3. Enter the DEV Tunnel ID and API key.
4. Credentials are persisted outside the install/update root at `%LOCALAPPDATA%\Zagent\Credentials\development\transport.credentials.json`; the API key remains DPAPI CurrentUser protected. A legacy credential under `dev\data\tunnel\config` is migrated automatically on first DEV startup after this change.
5. Start All.
6. Connect the Zagent Dev Plugin to the DEV tunnel.
7. Validate live ChatGPT routing before any new production bundle is created.

Do not place Tunnel API keys in source files, scripts, documentation, or chat logs.

## Current lifecycle validation

- Debug build: 0 warnings / 0 errors.
- Supervisor: 11/11 PASS.
- Manager: 15/15 PASS.
- Live DEV `lifecycle.all start`: 4 running processes.
- Live DEV `lifecycle.all stop`: 0 running processes.
- Files and Web stop correctly in DEV.
- Final DEV cleanup: 0 remaining Zagent/Python/Node processes.
- Manager source contains an explicit close confirmation warning before Core shutdown.

## Current development rule

Edit source -> build Debug -> run DEV -> test via Manager and ChatGPT Dev Plugin -> fix/retest -> only bundle after DEV acceptance.

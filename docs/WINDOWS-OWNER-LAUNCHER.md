# Zagent Multi Platform — independent launcher

The launcher opens the Core-hosted Web Dashboard. It is not a WPF Manager, a Dev/Production plugin or an additional process supervisor.

## Installed layout

Double-click Zagent.Launcher.exe in the selected installed Zagent root. The product must have a payload-manifest.json, Zagent.Core.exe, Zagent.Launcher.exe and packaged agent runtimes:

- agents/files/runtime/python/python.exe
- agents/tunnel/runtime/python/python.exe
- agents/arcmap/runtime/python/python.exe
- agents/web/runtime/node/node.exe
- agents/web/engine/dist/index.js

The installed Core and Launcher are self-contained win-x64. No sibling appBridge .NET SDK or local Zagent-Envs dependency is used.

The default DataRoot is the selected install root's data folder. Its config subfolder must contain zagent.machine.json, installed-manifest.json, dashboard.json and internal-secrets.dpapi.json. When Setup installs with a custom DataRoot, it stores the exact path in that installation's own HKCU Uninstall registration (installation-root fingerprint). Launcher reads that path without searching other Zagent products. For owner-controlled diagnostic overrides, the explicit ZAGENT_LAUNCHER_DATA_ROOT process environment variable takes precedence. Both machine config and installed manifest must bind InstallRoot and DataRoot to the selected installation, regardless of how the path was discovered. Owner-only ACL checks on the data/config directories and private dashboard/DPAPI files are mandatory. Generated machine/installed manifests may inherit ACLs from the already protected config directory. The launcher does not read encrypted secret contents, scan local application data for other Zagent products, copy credentials or auto-provision.

The launcher filters inherited sibling-plugin access, internal-token, device and supervisor overrides before dispatching a new Core child. Core remains the sole owner of supervisor lease, certificate/DPAPI verification, MCP OAuth resource authorization and Dashboard browser activation.

## Source checkout (developer mode)

A launcher in artifacts/launcher-win-x64 can locate its source checkout using component-manifest.json and the Core csproj without relying on Start-OwnerCore.ps1. Source mode requires an already provisioned checkout-local DataRoot and a built Debug Core and Web dist. Specify these runtime paths explicitly; no silent fallback to Zagent Dev or Production occurs:

- ZAGENT_LAUNCHER_DOTNET_ROOT: directory containing dotnet.exe
- ZAGENT_LAUNCHER_FILES_PYTHON: absolute Python interpreter path
- ZAGENT_LAUNCHER_TUNNEL_PYTHON: absolute Python interpreter path
- ZAGENT_LAUNCHER_WEB_NODE: absolute Node executable path
- ZAGENT_LAUNCHER_ARCMAP_PYTHON: absolute Python interpreter path
- ZAGENT_LAUNCHER_DATA_ROOT: only when DataRoot is not checkout/data

## Build and test

Run dotnet build Zagent.slnx -c Release. Run dotnet run --project tests/Zagent.LauncherTests -c Release -- <approved-dotnet-path>. Publish the launcher using packaging/scripts/Publish-Launcher.ps1 with -Dotnet and -OutputRoot specifying a fresh root. It produces launcher/Zagent.Launcher.exe as a self-contained single file.

Build-ProductionPayload.ps1 requires the launcher published alongside Core and Setup; it copies the launcher into the payload and includes its digest in payload-manifest.json. Installer Windows shortcuts target the installed launcher.

The launcher test suite uses disposable fixture paths, strict Windows ACL checks, a Core lease fixture and fake child activation. It never starts live Core. Production/client end-to-end acceptance and Windows code-signing are separate release gates.

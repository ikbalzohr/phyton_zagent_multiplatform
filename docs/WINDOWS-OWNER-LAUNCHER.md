# Windows owner dashboard launcher

Double-click `artifacts\launcher-win-x64\Zagent.Launcher.exe` in the installed checkout. Keep the entire published directory together; the EXE alone is not a self-contained application. This is a Windows x64 GUI apphost, not a console script or a debug no-op.

The launcher walks upward from its own directory to find the checkout. Do not move it to the Desktop; create a shortcut to the published EXE instead. Its framework-dependent apphost searches `../../../appBridge/toolchain/dotnet10` relative to the published directory first, then DOTNET_ROOT/global runtime locations. The enrolled installation uses the sibling portable .NET 10 runtime. The launcher requires Microsoft.NETCore.App 10.0 (compatible servicing patches roll forward); it does not require Windows Desktop Runtime.

Activation reuses the existing `Start-OwnerCore.ps1` startup contract: the built `src\Zagent.Core\bin\Debug\net10.0\Zagent.Core.exe --dashboard --root <checkout> --data-root <existing-root> --dashboard-config <existing-root>\config\dashboard.json`, with the portable DOTNET_ROOT and isolated Files/Tunnel Python environment. It does not execute the interactive PowerShell script, build Core, enroll, parse private secrets, repair ACLs, register startup, kill processes or restart a running Core. Core remains responsible for DPAPI/certificate validation and its existing supervisor lease/dashboard browser activation.

Existing enrollment discovery checks checkout `dev\data`, checkout `data`, and local application-data directories matching `*Zagent*`. Exactly one directory must contain both existing dashboard and DPAPI-secret files. Missing or ambiguous enrollment fails closed. Owner-only ACLs, plain paths and required Core/runtime files are checked before child dispatch. A failed launch displays a fixed message that closes after 15 seconds. Initial child-exit observation is bounded to 2 seconds; this is not a dashboard-health guarantee. Later failures must be diagnosed using existing Core diagnostics.

## Publish on the owner machine

From the checkout root in a normal owner PowerShell session:

```powershell
$dotnet = 'D:\3-Ikbalzohr\Agent\appBridge\toolchain\dotnet10\dotnet.exe'
& $dotnet publish src/Zagent.Launcher/Zagent.Launcher.csproj --configuration Release --runtime win-x64 --self-contained false --output artifacts/launcher-win-x64 --configfile tests/Zagent.LauncherTests/NuGet.Config
if ($LASTEXITCODE -ne 0) { throw 'Launcher publish failed' }
Get-FileHash artifacts/launcher-win-x64/Zagent.Launcher.exe -Algorithm SHA256
```

Keep `Zagent.Launcher.exe`, `Zagent.Launcher.dll`, `Zagent.Launcher.runtimeconfig.json`, and `Zagent.Launcher.deps.json`. PDB is optional. No private enrollment files are packaged.

## Isolated Windows fixtures — do not start Core

```powershell
& $dotnet run --project tests/Zagent.LauncherTests --configuration Release -- $dotnet
```

The fixture uses fresh disposable directories, actual owner ACL APIs, a GUID-named real Core supervisor lease, fake activation callbacks and a real fake-child process through the specified approved dotnet host. It validates exact argument boundaries, incomplete Core payload, missing isolated Python, ambiguous enrollment, unsafe ACL, repeated activation, lease exclusion/release and bounded child exit observation. It never executes Core or the fixture placeholder executables. Pass only the approved dotnet host path as its single argument.

Optional read-only installed-enrollment preflight, with activation explicitly suppressed:

```powershell
& $dotnet run --project tests/Zagent.LauncherTests -- --preflight-existing 'D:\3-Ikbalzohr\Agent\phyton_zagent_multiplatform' 'C:\Users\fazrin\AppData\Local'
```

Files MCP command environments may omit known-folder variables required by NuGet. Restore those process environment values only from Windows SHGetFolderPathW before invoking the exact approved dotnet path. Do not change global environment, policies or credentials.

Published artifact verification and these fixtures do not claim a live owner double-click, browser opening, certificate/DPAPI unlock or live Core health check. Do not perform a live activation/restart through MCP without separate authorization, because it can disconnect the active transport.

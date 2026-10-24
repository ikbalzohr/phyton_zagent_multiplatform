[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][string]$InstallRoot,
    [string]$DataRoot = '',
    [Parameter(Mandatory=$true)][string]$DotnetRoot,
    [string]$CoreExecutable = ''
)
# Launch existing owner enrollment only. No builds, password changes, import, startup registration or agent auto-start.
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'WindowsDashboard-Provisioning.ps1')
Assert-ZagentOwnerConsole
$InstallRoot = (Resolve-Path -LiteralPath $InstallRoot).Path
Assert-ZagentPlainPath $InstallRoot
$DotnetRoot = (Resolve-Path -LiteralPath $DotnetRoot).Path
if (-not (Test-Path -LiteralPath (Join-Path $DotnetRoot 'dotnet.exe') -PathType Leaf)) { throw 'Portable dotnet.exe missing.' }
if (-not $DataRoot) {
    # Inspect paths, not contents of credentials. Refuse an ambiguous choice instead of creating a new root.
    $candidates = @((Join-Path $InstallRoot 'dev\data'), (Join-Path $InstallRoot 'data'))
    $candidates += @(Get-ChildItem -LiteralPath $env:LOCALAPPDATA -Directory -Filter '*Zagent*' | ForEach-Object { $_.FullName })
    $matches = @($candidates | Select-Object -Unique | Where-Object { Test-Path -LiteralPath (Join-Path $_ 'config\dashboard.json') -PathType Leaf })
    if ($matches.Count -eq 1) { $DataRoot = $matches[0] }
    else {
        Write-Host 'Existing DataRoot candidates (paths only):'
        $matches | ForEach-Object { Write-Host $_ }
        $DataRoot = Read-Host 'Enter the DataRoot used for the existing dashboard; no new enrollment will be created'
    }
}
if (-not $DataRoot) { throw 'An existing owner DataRoot is required.' }
$DataRoot = (Resolve-Path -LiteralPath $DataRoot).Path
Assert-ZagentPlainPath $DataRoot
Assert-ZagentOwnerAcl $DataRoot
$config = Join-Path $DataRoot 'config\dashboard.json'
$internal = Join-Path $DataRoot 'config\internal-secrets.dpapi.json'
foreach ($file in @($config, $internal)) {
    if (-not (Test-Path -LiteralPath $file -PathType Leaf)) { throw 'Existing dashboard/internal provisioning is missing. Do not reprovision or delete data.' }
    Assert-ZagentPlainPath $file
    Assert-ZagentOwnerAcl $file
}
if (-not $CoreExecutable) { $CoreExecutable = Join-Path $InstallRoot 'src\Zagent.Core\bin\Debug\net10.0\Zagent.Core.exe' }
$CoreExecutable = (Resolve-Path -LiteralPath $CoreExecutable).Path
if (-not (Test-Path -LiteralPath $CoreExecutable -PathType Leaf)) { throw 'Build the Core Windows apphost first.' }
Assert-ZagentPlainPath $CoreExecutable
if (-not (Test-Path -LiteralPath (Join-Path $InstallRoot 'agents\web\engine\dist\index.js') -PathType Leaf)) { throw 'Previously built Web entrypoint missing; stop and restore the reviewed Web build.' }
$tunnelPython = $env:ZAGENT_TUNNEL_PYTHON
if (-not $tunnelPython) { $tunnelPython = Join-Path $env:LOCALAPPDATA 'Zagent-Envs\tunnel\Scripts\python.exe' }
if (-not (Test-Path -LiteralPath $tunnelPython -PathType Leaf)) { throw 'Known isolated Tunnel Python missing; no fallback to legacy Python.' }
$previousDotnet = $env:DOTNET_ROOT
$previousTunnel = $env:ZAGENT_TUNNEL_PYTHON
try {
    $env:DOTNET_ROOT = $DotnetRoot
    $env:ZAGENT_TUNNEL_PYTHON = $tunnelPython
    Write-Host ('Using existing DataRoot: ' + $DataRoot)
    Write-Host 'Opening the local dashboard. Use its local admin account, not the OAuth account.'
    & $CoreExecutable --dashboard --root $InstallRoot --data-root $DataRoot --dashboard-config $config
    if ($LASTEXITCODE -ne 0) { throw 'Core exited unsuccessfully; preserve the error and stop.' }
}
finally {
    $env:DOTNET_ROOT = $previousDotnet
    $env:ZAGENT_TUNNEL_PYTHON = $previousTunnel
}

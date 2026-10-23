[CmdletBinding()]
param(
    [switch]$NoBuild,
    [string]$Dotnet = 'dotnet',
    [string]$DashboardConfig = '',
    [string]$DataRoot = '',
    [string]$FilesProfile = '',
    [string]$Python311 = '',
    [string]$WebNode = ''
)
$ErrorActionPreference = 'Stop'
$Root = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
. (Join-Path $Root 'packaging\scripts\WindowsDashboard-Provisioning.ps1')
Assert-ZagentOwnerConsole
if (-not $DataRoot) { $DataRoot = Join-Path $PSScriptRoot 'data' }
$DataRoot = [IO.Path]::GetFullPath($DataRoot)
if (-not $DashboardConfig) { $DashboardConfig = Join-Path $DataRoot 'config\dashboard.json' }
$DashboardConfig = [IO.Path]::GetFullPath($DashboardConfig)
if ($DashboardConfig -ine (Join-Path $DataRoot 'config\dashboard.json')) { throw 'Dashboard config must belong to this DataRoot; no cross-install config.' }
foreach ($path in @($DataRoot,(Join-Path $DataRoot 'config'),$DashboardConfig,(Join-Path $DataRoot 'config\internal-secrets.dpapi.json'),(Join-Path $DataRoot 'dashboard-keys'))) {
    if (-not (Test-Path -LiteralPath $path)) { throw 'Dashboard NOT_CONFIGURED: provision owner ACL, localhost certificate, internal DPAPI secrets and account first.' }
    Assert-ZagentOwnerAcl $path
}
$config = Get-Content -LiteralPath $DashboardConfig -Raw | ConvertFrom-Json
Assert-ZagentDashboardOrigin $config.Url
# Deliberately never build/install on launch. -NoBuild retained for existing invocations.
$tfm = ([xml](Get-Content -LiteralPath (Join-Path $Root 'src\Zagent.Core\Zagent.Core.csproj') -Raw)).Project.PropertyGroup.TargetFramework | Where-Object { $_ } | Select-Object -First 1
$core = Join-Path $Root "src\Zagent.Core\bin\Debug\$tfm\Zagent.Core.exe"
if (-not (Test-Path -LiteralPath $core -PathType Leaf)) { throw "Build Core explicitly on Windows first: $core" }
Assert-ZagentPlainPath $core
$dotnetPath = (Get-Command $Dotnet -CommandType Application -ErrorAction Stop).Source
$version = (& $dotnetPath --version | Out-String).Trim()
if ($LASTEXITCODE -ne 0 -or $version -cne '10.0.401') { throw 'Select the approved .NET SDK 10.0.401 dotnet.exe explicitly with -Dotnet; no SDK installation or fallback is attempted.' }
if (-not $FilesProfile) { $FilesProfile = Join-Path $PSScriptRoot 'workspace' }
$FilesProfile = [IO.Path]::GetFullPath($FilesProfile)
Assert-ZagentPlainPath $FilesProfile
if ($FilesProfile.TrimEnd('\') -eq $Root.TrimEnd('\') -or $FilesProfile -eq [IO.Path]::GetPathRoot($FilesProfile)) { throw 'Use a disposable explicit local workspace, never the repository or drive root.' }
$values = @{
    ZAGENT_ENVIRONMENT = 'DEVELOPMENT'; ZAGENT_ROOT = $Root; ZAGENT_DATA_ROOT = $DataRoot
    ZAGENT_FILES_DEFAULT_PROFILE = $FilesProfile; ZAGENT_MANAGER_PIPE = 'Zagent.Manager.Development'
    ZAGENT_SUPERVISOR_LEASE_NAME = 'Local\Zagent.v1.Supervisor.Development'; ZAGENT_BIND_HOST = '127.0.0.3'
    ZAGENT_TUNNEL_PORT = '19010'; ZAGENT_TUNNEL_HEALTH_PORT = '19011'; ZAGENT_FILES_PORT = '19020'
    ZAGENT_WEB_PORT = '19030'; ZAGENT_ARCMAP_PORT = '19040'; DOTNET_ROOT = (Split-Path $dotnetPath -Parent)
    DOTNET_ROOT_X64 = (Split-Path $dotnetPath -Parent)
}
if ($Python311) {
    $Python311 = (Resolve-Path -LiteralPath $Python311).Path
    Assert-ZagentPlainPath $Python311
    $pythonVersion = (& $Python311 -I -S -c 'import sys; print("%d.%d" % sys.version_info[:2])' | Out-String).Trim()
    if ($LASTEXITCODE -ne 0 -or $pythonVersion -cne '3.11') { throw 'Optional Python must be 3.11; no dependencies are installed and ArcGIS 2.7 is never modified.' }
    foreach ($agent in @('FILES','TUNNEL','ARCMAP')) { $values[('ZAGENT_'+$agent+'_PYTHON')] = $Python311 }
}
if ($WebNode) { $values['ZAGENT_WEB_NODE'] = (Resolve-Path -LiteralPath $WebNode).Path }
# Dashboard creation itself does not require Python, Node, ArcMap or tunnel-client.
# Starting an agent later requires its real runtime/dependencies; an overview is not MCP readiness.
$previous = @{}
try {
    foreach ($name in $values.Keys) { $previous[$name] = [Environment]::GetEnvironmentVariable($name,'Process'); [Environment]::SetEnvironmentVariable($name,$values[$name],'Process') }
    & $core --dashboard --root $Root --data-root $DataRoot --files-profile $FilesProfile --dashboard-config $DashboardConfig
    if ($LASTEXITCODE -ne 0) { throw "DEV Core dashboard failed ($LASTEXITCODE)." }
} finally {
    foreach ($name in $previous.Keys) { [Environment]::SetEnvironmentVariable($name,$previous[$name],'Process') }
}

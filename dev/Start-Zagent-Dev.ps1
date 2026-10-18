param([switch]$NoBuild, [string]$Dotnet = 'dotnet', [string]$DashboardConfig = '', [string]$FilesProfile = '')
$ErrorActionPreference = 'Stop'
if ($env:OS -ne 'Windows_NT') { throw 'Local Windows only.' }
$Root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$DataRoot = Join-Path $PSScriptRoot 'data'
if (-not $DashboardConfig) { $DashboardConfig = Join-Path $DataRoot 'config\dashboard.json' }
if (-not (Test-Path $DashboardConfig -PathType Leaf)) { throw 'Dashboard NOT_CONFIGURED: provision owner ACL, certificate and account first. No unauthenticated fallback.' }
if (-not $NoBuild) { & (Join-Path $PSScriptRoot 'Build-ZagentDev.ps1') -Dotnet $Dotnet }
if (-not $FilesProfile) { $FilesProfile = Join-Path $PSScriptRoot 'workspace' }
$tfm = ([xml](Get-Content (Join-Path $Root 'src\Zagent.Core\Zagent.Core.csproj') -Raw)).Project.PropertyGroup.TargetFramework | Where-Object { $_ } | Select-Object -First 1
$core = Join-Path $Root "src\Zagent.Core\bin\Debug\$tfm\Zagent.Core.exe"
if (-not (Test-Path $core)) { throw "Core DEV executable missing: $core" }
$env:ZAGENT_ENVIRONMENT = 'DEVELOPMENT'
$env:ZAGENT_ROOT = $Root
$env:ZAGENT_DATA_ROOT = $DataRoot
$env:ZAGENT_FILES_DEFAULT_PROFILE = [IO.Path]::GetFullPath($FilesProfile)
$env:ZAGENT_MANAGER_PIPE = 'Zagent.Manager.Development'
$env:ZAGENT_SUPERVISOR_LEASE_NAME = 'Local\Zagent.v1.Supervisor.Development'
$env:ZAGENT_BIND_HOST = '127.0.0.3'
$env:ZAGENT_TUNNEL_PORT = '19010'
$env:ZAGENT_TUNNEL_HEALTH_PORT = '19011'
$env:ZAGENT_FILES_PORT = '19020'
$env:ZAGENT_WEB_PORT = '19030'
$env:ZAGENT_ARCMAP_PORT = '19040'
foreach ($agent in @('FILES','TUNNEL','ARCMAP')) {
    $python = Join-Path $PSScriptRoot ("runtime\"+$agent.ToLowerInvariant()+"-python-3.11.9\python.exe")
    if (-not (Test-Path $python)) { throw "Prepare isolated DEV runtime first: $python" }
    [Environment]::SetEnvironmentVariable("ZAGENT_"+$agent+"_PYTHON",$python)
}
$env:ZAGENT_WEB_NODE = Join-Path $PSScriptRoot 'runtime\node-24.19.0\node.exe'
# No production upstream autodiscovery, shared IPC, source profile, or agent config rewrite.
& $core --dashboard --root $Root --data-root $DataRoot --files-profile $env:ZAGENT_FILES_DEFAULT_PROFILE --dashboard-config $DashboardConfig
if ($LASTEXITCODE -ne 0) { throw "DEV Core dashboard failed ($LASTEXITCODE)." }

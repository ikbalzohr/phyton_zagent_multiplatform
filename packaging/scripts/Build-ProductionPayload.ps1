param(
  [Parameter(Mandatory=$true)]
  [string]$OutputRoot,
  [string]$RuntimeRoot = "",
  [string]$PublishRoot = ""
)

$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$OutputRoot = [IO.Path]::GetFullPath($OutputRoot)
if ($env:OS -ne "Windows_NT") { throw "Local Windows only." }
& (Join-Path $PSScriptRoot "Test-ReleaseSource.ps1") -Root $Root | Out-Null
$release = Get-Content (Join-Path $Root "component-manifest.json") -Raw | ConvertFrom-Json

# Fail closed if a previously fixed production bug regresses.
& (Join-Path $PSScriptRoot "Test-KnownBugRegressions.ps1") -Root $Root | Out-Null
# Fail closed if Chrome Bridge reverts to legacy Pair + timed authorization.
& (Join-Path $PSScriptRoot "Test-WebPersistentConsentBundle.ps1") -Root $Root | Out-Null

if (Test-Path $OutputRoot) {
  throw "Staging output already exists. Refusing to overwrite: $OutputRoot"
}

$runtime = if ($RuntimeRoot) { (Resolve-Path $RuntimeRoot).Path } else { Join-Path $Root "packaging\runtime" }
$publish = if ($PublishRoot) { (Resolve-Path $PublishRoot).Path } else { Join-Path $Root "packaging\publish" }

function Require-File([string]$Path) {
  if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
    throw "Required file missing: $Path"
  }
}

function Require-Dir([string]$Path) {
  if (-not (Test-Path -LiteralPath $Path -PathType Container)) {
    throw "Required directory missing: $Path"
  }
}

function Copy-Tree(
  [string]$Source,
  [string]$Destination,
  [string[]]$ExcludeDirs = @(),
  [string[]]$ExcludeFiles = @()
) {
  Require-Dir $Source
  New-Item -ItemType Directory -Force -Path $Destination | Out-Null

  $args = @(
    $Source,
    $Destination,
    "/E",
    "/COPY:DAT",
    "/DCOPY:DAT",
    "/R:1",
    "/W:1",
    "/NFL",
    "/NDL",
    "/NJH",
    "/NJS",
    "/NP"
  )

  if ($ExcludeDirs.Count -gt 0) {
    $args += "/XD"
    $args += $ExcludeDirs
  }

  if ($ExcludeFiles.Count -gt 0) {
    $args += "/XF"
    $args += $ExcludeFiles
  }

  & robocopy @args | Out-Null
  if ($LASTEXITCODE -gt 7) {
    throw "robocopy failed ($LASTEXITCODE): $Source -> $Destination"
  }
}

function Set-EmbeddedPythonPath([string]$PythonRoot) {
  $pth = Join-Path $PythonRoot "python311._pth"
  @(
    "python311.zip",
    ".",
    "Lib\site-packages",
    "..\..\engine",
    "import site"
  ) | Set-Content -LiteralPath $pth -Encoding ASCII
}

$core = Join-Path $publish "core\Zagent.Core.exe"
$setup = Join-Path $publish "setup\Zagent.Setup.exe"
$launcher = Join-Path $publish "launcher\Zagent.Launcher.exe"
Require-File $core
Require-File $setup
Require-File $launcher

foreach ($name in @(
  "files-python-3.11.9",
  "tunnel-python-3.11.9",
  "arcmap-python-3.11.9",
  "web-prod",
  "playwright-browsers-1.63.0-final"
)) {
  Require-Dir (Join-Path $runtime $name)
}

New-Item -ItemType Directory -Force -Path $OutputRoot | Out-Null
Copy-Tree (Join-Path $publish "core") $OutputRoot
Copy-Item -LiteralPath $setup -Destination (Join-Path $OutputRoot "Zagent.Setup.exe")
Copy-Item -LiteralPath $launcher -Destination (Join-Path $OutputRoot "Zagent.Launcher.exe")
# Passwordless local-owner first-run is separate from remote MCP OAuth.
# HTTPS trust requires explicit CurrentUser consent on the first click.
Copy-Item -LiteralPath (Join-Path $PSScriptRoot "FirstRun-ZagentMultiPlatform.ps1") -Destination $OutputRoot
$setupScripts = Join-Path $OutputRoot "setup"
New-Item -ItemType Directory -Force -Path $setupScripts | Out-Null
foreach ($helper in @("Provision-WindowsDashboard.ps1", "WindowsDashboard-Provisioning.ps1")) {
  Copy-Item -LiteralPath (Join-Path $PSScriptRoot $helper) -Destination $setupScripts
}
Copy-Item -LiteralPath (Join-Path $Root "component-manifest.json") -Destination $OutputRoot

$agentsOut = Join-Path $OutputRoot "agents"
New-Item -ItemType Directory -Force -Path $agentsOut | Out-Null


# Files
$filesOut = Join-Path $agentsOut "files"
Copy-Tree (Join-Path $Root "agents\files\engine") (Join-Path $filesOut "engine") @("__pycache__","tests","docs") @("*.pyc","_probe_*")
Copy-Item -LiteralPath (Join-Path $Root "agents\files\files.component.json") -Destination $filesOut
Copy-Item -LiteralPath (Join-Path $Root "agents\files\runtime-tools.snapshot.json") -Destination $filesOut
Copy-Tree (Join-Path $runtime "files-python-3.11.9") (Join-Path $filesOut "runtime\python") @("__pycache__") @("*.pyc")
Set-EmbeddedPythonPath (Join-Path $filesOut "runtime\python")

# Tunnel
$tunnelOut = Join-Path $agentsOut "tunnel"
Copy-Tree (Join-Path $Root "agents\tunnel\engine") (Join-Path $tunnelOut "engine") @("__pycache__","tests","docs") @("*.pyc","_probe_*")
Copy-Tree (Join-Path $Root "agents\tunnel\transport") (Join-Path $tunnelOut "transport")
Copy-Item -LiteralPath (Join-Path $Root "agents\tunnel\tunnel.component.json") -Destination $tunnelOut
Copy-Tree (Join-Path $runtime "tunnel-python-3.11.9") (Join-Path $tunnelOut "runtime\python") @("__pycache__") @("*.pyc")
Set-EmbeddedPythonPath (Join-Path $tunnelOut "runtime\python")

# Web
$webOut = Join-Path $agentsOut "web"
$webEngine = Join-Path $webOut "engine"
New-Item -ItemType Directory -Force -Path $webEngine | Out-Null
Copy-Tree (Join-Path $Root "agents\web\engine\dist") (Join-Path $webEngine "dist")
Copy-Tree (Join-Path $Root "agents\web\engine\extension") (Join-Path $webEngine "extension")
if (Test-Path (Join-Path $Root "agents\web\engine\artifacts\chrome-bridge")) {
  Copy-Tree (Join-Path $Root "agents\web\engine\artifacts\chrome-bridge") (Join-Path $webEngine "artifacts\chrome-bridge")
}

$productionBridgeTargets = @(
  (Join-Path $webEngine "extension"),
  (Join-Path $webEngine "artifacts\chrome-bridge")
)
& (Join-Path $Root "packaging\scripts\Set-ChromeBridgeEnvironment.ps1") -Environment "PRODUCTION" -BindHost "127.0.0.3" -Port 0 -TargetRoots $productionBridgeTargets | Out-Null

foreach ($bridgeTarget in $productionBridgeTargets) {
  $bridgeConfigPath = Join-Path $bridgeTarget "bridge-config.json"
  $bridgeConfig = Get-Content -LiteralPath $bridgeConfigPath -Raw | ConvertFrom-Json
  if ($bridgeConfig.environment -ne "PRODUCTION") {
    throw "Production Chrome Bridge artifact has the wrong environment: $bridgeConfigPath"
  }
  if ($bridgeConfig.configured -ne $false) {
    throw "Production Chrome Bridge artifact must remain installation-managed and unconfigured at packaging time: $bridgeConfigPath"
  }
  if ($null -ne $bridgeConfig.defaultBase) {
    throw "Production payload must not hard-code a Chrome Bridge endpoint: $bridgeConfigPath"
  }
  $rawBridgeConfig = Get-Content -LiteralPath $bridgeConfigPath -Raw
  if ($rawBridgeConfig -match '18830|19030') {
    throw "A fixed Chrome Bridge port leaked into the production payload: $bridgeConfigPath"
  }
}

Copy-Tree (Join-Path $runtime "web-prod\node_modules") (Join-Path $webEngine "node_modules") @(".cache") @()
Copy-Item -LiteralPath (Join-Path $Root "agents\web\engine\package.json") -Destination $webEngine
Copy-Item -LiteralPath (Join-Path $Root "agents\web\web.component.json") -Destination $webOut
Copy-Item -LiteralPath (Join-Path $Root "agents\web\runtime-tools.snapshot.json") -Destination $webOut

$webNode = Join-Path $webOut "runtime\node"
New-Item -ItemType Directory -Force -Path $webNode | Out-Null
Copy-Item -LiteralPath (Join-Path $runtime "node-24.19.0\node.exe") -Destination $webNode
Copy-Item -LiteralPath (Join-Path $runtime "node-24.19.0\LICENSE") -Destination $webNode
$browserSource = Join-Path $runtime "playwright-browsers-1.63.0-final"
$browserDestination = Join-Path $webOut "runtime\browsers"
New-Item -ItemType Directory -Force -Path $browserDestination | Out-Null

$forbiddenBrowserDirs = @(
  Get-ChildItem -LiteralPath $browserSource -Directory |
    Where-Object {
      $_.Name -like "chromium-*" -or
      $_.Name -like "chromium_headless_shell-*" -or
      $_.Name -like "firefox-*" -or
      $_.Name -like "webkit-*" -or
      $_.Name -like "winldd-*"
    }
)
if ($forbiddenBrowserDirs.Count -gt 0) {
  throw ("Unsupported browser payload found in production staging: " +
    (($forbiddenBrowserDirs | Select-Object -ExpandProperty Name) -join ","))
}

$ffmpegDir = Get-ChildItem -LiteralPath $browserSource -Directory |
  Where-Object { $_.Name -like "ffmpeg-*" } |
  Select-Object -First 1

if (-not $ffmpegDir) {
  throw "FFmpeg runtime missing; Chrome video recording capability would be lost."
}

Copy-Tree $ffmpegDir.FullName (Join-Path $browserDestination $ffmpegDir.Name)

& (Join-Path $PSScriptRoot "Build-ArcMapAddIn.ps1") | Out-Null
# ArcMap
$arcOut = Join-Path $agentsOut "arcmap"
$arcEngine = Join-Path $arcOut "engine"
New-Item -ItemType Directory -Force -Path $arcEngine | Out-Null

foreach ($part in @("arcmap_bridge","config","data_manager","mcp_server","orchestrator","profiles","stage2","stage3","vendor27")) {
  Copy-Tree (Join-Path $Root ("agents\arcmap\engine\" + $part)) (Join-Path $arcEngine $part) @("__pycache__","tests","docs") @("*.pyc","*.pytc","_probe_*")
}

foreach ($file in @("requirements-mcp.txt","VERSION","BUILD_INFO.json","BUILD_MANIFEST.json","ZAGENT_BUILD_INFO.json","README.md")) {
  $source = Join-Path $Root ("agents\arcmap\engine\" + $file)
  if (Test-Path $source) {
    Copy-Item -LiteralPath $source -Destination $arcEngine
  }
}

[IO.File]::WriteAllText((Join-Path $arcEngine "arcmap_bridge\bridge_runtime.json"), '{"schema_version":2,"environment":"PRODUCTION"}')
Copy-Item -LiteralPath (Join-Path $Root "agents\arcmap\arcmap.component.json") -Destination $arcOut
Copy-Item -LiteralPath (Join-Path $Root "agents\arcmap\runtime-tools.snapshot.json") -Destination $arcOut
Copy-Tree (Join-Path $runtime "arcmap-python-3.11.9") (Join-Path $arcOut "runtime\python") @("__pycache__") @("*.pyc")
Set-EmbeddedPythonPath (Join-Path $arcOut "runtime\python")
Copy-Tree (Join-Path $Root "agents\arcmap\artifacts") (Join-Path $arcOut "artifacts")

# ArcMap Orchestrator RC gate: fail closed before the installer is assembled.
Require-File (Join-Path $arcEngine "orchestrator\__init__.py")
Require-File (Join-Path $arcEngine "mcp_server\workflow_runtime_client.py")
Require-File (Join-Path $arcEngine "orchestrator\adapters\file_worker\arcgis_process.py")
Require-File (Join-Path $arcEngine "orchestrator\adapters\file_worker\worker27.py")

$arcSnapshot = Get-Content -LiteralPath (Join-Path $arcOut "runtime-tools.snapshot.json") -Raw | ConvertFrom-Json
$arcComponent = Get-Content -LiteralPath (Join-Path $arcOut "arcmap.component.json") -Raw | ConvertFrom-Json
if ([int]$arcSnapshot.count -le 0 -or [int]$arcComponent.public_tools.count -ne [int]$arcSnapshot.count) {
  throw "ArcMap candidate snapshot and component catalog counts disagree; reconcile candidate schemas/names on Windows."
}

$arcBridgeConfig = Get-Content -LiteralPath (Join-Path $arcEngine "arcmap_bridge\bridge_runtime.json") -Raw | ConvertFrom-Json
if ($arcBridgeConfig.environment -ne "PRODUCTION") {
  throw "ArcMap production bridge_runtime.json must be PRODUCTION."
}
if ($null -ne $arcBridgeConfig.data_root -or $null -ne $arcBridgeConfig.ipc_root) {
  throw "ArcMap production bridge_runtime.json must not embed a Dev/upstream data_root or ipc_root."
}


$notices = @"
Zagent production runtime notices

Python 3.11.9 embeddable x64
Source: https://www.python.org/downloads/release/python-3119/
Archive SHA256: 33b448f95fecb7c6f802157dbd5e6b40a2ad9bfc8b95ca634a06ba4073ad1ac0

Node.js 24.19.0 win-x64
Source: https://nodejs.org/dist/v24.19.0/
Archive SHA256: 57f71ab3652e797d84acddc79c81cc9ff1c6ddb2a1974cdb83f00fee9bff4c73

Playwright 1.63.0 automation runtime
Google Chrome is external and is not bundled.
No Chromium, Firefox, or WebKit browser binaries are bundled.
FFmpeg is bundled under agents\web\runtime\browsers only to preserve Chrome video recording.

ArcMap Desktop 10.6.1 is external software and is not bundled with Zagent.
"@
[IO.File]::WriteAllText(
  (Join-Path $OutputRoot "THIRD_PARTY_RUNTIME_NOTICES.txt"),
  $notices,
  [Text.UTF8Encoding]::new($false)
)

$forbiddenPatterns = @(
  "D:\3-Ikbalzohr\Agent\ZohrFiles",
  "D:\3-Ikbalzohr\Agent\ZohrTunnel",
  "D:\3-Ikbalzohr\Agent\ZohrWeb",
  "D:\3-Ikbalzohr\ArcMapAgent\Work",
  "C:\Users\fazrin\AppData\Local\Programs\Python",
  "C:\Program Files\nodejs"
)

$textExtensions = @(
  ".json",".txt",".md",".py",".pyt",".js",".mjs",".html",".css",
  ".xml",".cfg",".ini",".toml",".yaml",".yml","._pth"
)

$forbiddenHits = @()
Get-ChildItem -LiteralPath $OutputRoot -Recurse -File | ForEach-Object {
  $ext = $_.Extension.ToLowerInvariant()
  if ($textExtensions -contains $ext -or $_.Name -eq "python311._pth") {
    try {
      $content = [IO.File]::ReadAllText($_.FullName)
      foreach ($pattern in $forbiddenPatterns) {
        if ($content.Contains($pattern,[StringComparison]::OrdinalIgnoreCase)) {
          $forbiddenHits += [pscustomobject]@{
            file = $_.FullName.Substring($OutputRoot.Length).TrimStart("\")
            pattern = $pattern
          }
        }
      }
    } catch {
    }
  }
}

if ($forbiddenHits.Count -gt 0) {
  $details = $forbiddenHits | ConvertTo-Json -Depth 4
  throw "Forbidden developer/legacy paths found in staging: $details"
}

$manifestPath = Join-Path $OutputRoot "payload-manifest.json"
$payloadFiles = Get-ChildItem -LiteralPath $OutputRoot -Recurse -File |
  Where-Object { $_.FullName -ne $manifestPath } |
  Sort-Object FullName

$entries = foreach ($file in $payloadFiles) {
  [pscustomobject]@{
    path = $file.FullName.Substring($OutputRoot.Length).TrimStart("\").Replace("\","/")
    size = $file.Length
    sha256 = (Get-FileHash -LiteralPath $file.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
  }
}

$totalBytes = ($payloadFiles | Measure-Object Length -Sum).Sum
$payload = [pscustomobject]@{
  schema_version = "1.0"
  product = "Zagent"
  core_version = $release.components.core.canonical_version
  suite_version = $release.suite_version
  product_line = $release.product_line
  components = $release.components
  platform = "win-x64"
  install_root_policy = "BASE_FOLDER_PLUS_ZAGENT"
  default_data_root = "<InstallRoot>\data"
  default_files_profile = "<InstallRoot>\workspace"
  file_count = $entries.Count
  total_bytes = $totalBytes
  generated_at_utc = [DateTimeOffset]::UtcNow.ToString("o")
  runtime = [pscustomobject]@{
    dotnet = "self-contained"
    files_python = "3.11.9-embedded"
    tunnel_python = "3.11.9-embedded"
    arcmap_python = "3.11.9-embedded"
    node = "24.19.0-portable"
    playwright = "1.63.0"
    browsers = @()
    external_browser = "google-chrome"
    chromium_bundled = $false
    firefox_bundled = $false
    webkit_bundled = $false
    ffmpeg_bundled = $true
  }
  files = $entries
}

[IO.File]::WriteAllText(
  $manifestPath,
  (($payload | ConvertTo-Json -Depth 8) + [Environment]::NewLine),
  [Text.UTF8Encoding]::new($false)
)

[pscustomobject]@{
  ok = $true
  output_root = $OutputRoot
  file_count = $entries.Count + 1
  size_mb = [math]::Round($totalBytes / 1MB,2)
  manifest = $manifestPath
  forbidden_path_hits = $forbiddenHits.Count
} | ConvertTo-Json
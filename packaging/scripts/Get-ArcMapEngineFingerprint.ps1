param(
  [string]$Root = "",
  [string]$EngineRoot = ""
)

$ErrorActionPreference = "Stop"

if ([string]::IsNullOrWhiteSpace($Root)) {
  $scriptsDir = Split-Path -Parent $PSScriptRoot
  $Root = Split-Path -Parent $scriptsDir
}
$Root = [IO.Path]::GetFullPath([string]$Root)

if ([string]::IsNullOrWhiteSpace($EngineRoot)) {
  $EngineRoot = [IO.Path]::Combine($Root, "agents", "arcmap", "engine")
}
$EngineRoot = [IO.Path]::GetFullPath([string]$EngineRoot)

if (-not [IO.Directory]::Exists($EngineRoot)) {
  throw "ArcMap engine root missing: $EngineRoot"
}

$metadataNames = @(
  "BUILD_INFO.json",
  "BUILD_MANIFEST.json",
  "ZAGENT_BUILD_INFO.json"
)

function Get-RelativePath([string]$Path) {
  return $Path.Substring($EngineRoot.Length).TrimStart([char]92).Replace([char]92, [char]47)
}

function Get-StringSha256([string]$Value) {
  $sha = [Security.Cryptography.SHA256]::Create()
  try {
    $bytes = [Text.UTF8Encoding]::new($false).GetBytes($Value)
    return ([BitConverter]::ToString($sha.ComputeHash($bytes))).Replace("-", "").ToLowerInvariant()
  }
  finally {
    $sha.Dispose()
  }
}

$files = Get-ChildItem -LiteralPath $EngineRoot -Recurse -File |
  Where-Object {
    $lower = $_.FullName.ToLowerInvariant()
    -not $lower.Contains("\vendor27\") -and
    -not $lower.Contains("\__pycache__\") -and
    $_.Extension -ne ".pyc" -and
    $_.Name -ne "bridge_runtime.json" -and
    $_.Name -notlike "*.bak_*" -and
    $metadataNames -notcontains $_.Name
  } |
  Sort-Object { (Get-RelativePath $_.FullName).ToLowerInvariant() }

$lines = @()
foreach ($file in $files) {
  $relative = Get-RelativePath $file.FullName
  $digest = (Get-FileHash -LiteralPath $file.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
  $lines += ($relative + ":" + $digest)
}

$result = [ordered]@{
  schema_version = "2.0"
  files = $files.Count
  aggregate_sha256 = Get-StringSha256 ($lines -join [char]10)
  method = "sha256(sorted case-insensitive relative_path:file_sha256 lines; slash=/; utf8-no-bom; LF; no-final-newline)"
  exclusions = @(
    "vendor27/**",
    "**/__pycache__/**",
    "**/*.pyc",
    "**/bridge_runtime.json",
    "**/*.bak_*",
    "BUILD_INFO.json",
    "BUILD_MANIFEST.json",
    "ZAGENT_BUILD_INFO.json"
  )
  self_referential_metadata_excluded = $true
  stage3_bridge_sha256 = (Get-FileHash -LiteralPath (Join-Path $EngineRoot "stage3\bridge.py") -Algorithm SHA256).Hash.ToLowerInvariant()
}

$result | ConvertTo-Json -Depth 6

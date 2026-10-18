param(
  [Parameter(Mandatory=$true)]
  [ValidateSet("DEVELOPMENT","PRODUCTION")]
  [string]$Environment,

  [Parameter(Mandatory=$true)]
  [string]$BindHost,

  [Parameter(Mandatory=$true)]
  [ValidateRange(0,65535)]
  [int]$Port,

  [Parameter(Mandatory=$true)]
  [string[]]$TargetRoots
)

$ErrorActionPreference = "Stop"

if ($BindHost -notin @("127.0.0.1","127.0.0.3","localhost")) {
  throw "Chrome Bridge host must be local loopback: $BindHost"
}

$configured = $Port -gt 0
if ($Environment -eq "DEVELOPMENT" -and -not $configured) {
  throw "Development Chrome Bridge must have an explicit runtime port."
}

$defaultBase = if ($configured) {
  "http://$($BindHost):$Port/bridge/"
} else {
  $null
}

$legacyBases = if (-not $configured) {
  @()
} elseif ($Environment -eq "PRODUCTION") {
  @(
    "http://127.0.0.3:19030/bridge/",
    "http://127.0.0.1:19030/bridge/",
    "http://127.0.0.1:8021/bridge/"
  )
} else {
  @(
    "http://127.0.0.3:18830/bridge/",
    "http://127.0.0.1:18830/bridge/",
    "http://127.0.0.1:8021/bridge/"
  )
}

if ($configured -and $legacyBases -contains $defaultBase) {
  throw "Bridge contract invalid: default endpoint is also marked legacy: $defaultBase"
}

$config = [ordered]@{
  schemaVersion = 2
  configured = $configured
  environment = $Environment
  defaultBase = $defaultBase
  legacyBases = $legacyBases
  generatedBy = if ($configured) {
    "Set-ChromeBridgeEnvironment.ps1"
  } else {
    "Production payload placeholder; Zagent.Core installation must configure this file."
  }
  generatedFrom = if ($configured) {
    "development runtime"
  } else {
    "installation pending"
  }
}

$json = $config | ConvertTo-Json -Depth 4

foreach ($root in $TargetRoots) {
  $full = [IO.Path]::GetFullPath($root)
  if (-not (Test-Path -LiteralPath $full -PathType Container)) {
    throw "Chrome Bridge target root missing: $full"
  }
  $manifest = Join-Path $full "manifest.json"
  $background = Join-Path $full "background.js"
  if (-not (Test-Path -LiteralPath $manifest -PathType Leaf) -or
      -not (Test-Path -LiteralPath $background -PathType Leaf)) {
    throw "Target is not a Zagent Chrome Bridge extension root: $full"
  }

  [IO.File]::WriteAllText(
    (Join-Path $full "bridge-config.json"),
    $json,
    [Text.UTF8Encoding]::new($false))
}

[pscustomobject]@{
  ok = $true
  configured = $configured
  environment = $Environment
  default_base = $defaultBase
  targets = @($TargetRoots)
} | ConvertTo-Json -Depth 4

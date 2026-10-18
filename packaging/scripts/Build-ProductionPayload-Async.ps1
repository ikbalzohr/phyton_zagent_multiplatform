param(
  [string]$OutputRoot = ""
)
$ErrorActionPreference = "Stop"
$root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
if ([string]::IsNullOrWhiteSpace($OutputRoot)) {
  $OutputRoot = Join-Path $root "packaging\staging\Zagent-1.0.0-build1"
}
$out = [IO.Path]::GetFullPath($OutputRoot)
$leaf = Split-Path $out -Leaf
$status = Join-Path $root ("packaging\staging\" + $leaf + ".build-status.json")
$log = Join-Path $root ("packaging\staging\" + $leaf + ".build.log")
New-Item -ItemType Directory -Force -Path (Split-Path $status) | Out-Null
function Save-Status([string]$state,[string]$message,[int]$code){
  [pscustomobject]@{
    state=$state;message=$message;exit_code=$code;output_root=$out;updated_at=(Get-Date).ToString("o")
  } | ConvertTo-Json | Set-Content -LiteralPath $status -Encoding UTF8
}
Save-Status "RUNNING" "Building production staging payload." -1
try {
  $result = & (Join-Path $root "packaging\scripts\Build-ProductionPayload.ps1") -OutputRoot $out 2>&1
  $invocationSucceeded = $?
  $result | Set-Content -LiteralPath $log -Encoding UTF8
  if(-not $invocationSucceeded){ Save-Status "FAILED" (($result|Out-String).Trim()) 1; exit 1 }
  Save-Status "PASS" (($result|Out-String).Trim()) 0
  exit 0
}
catch {
  $_ | Out-String | Set-Content -LiteralPath $log -Encoding UTF8
  Save-Status "FAILED" $_.Exception.Message 1
  exit 1
}

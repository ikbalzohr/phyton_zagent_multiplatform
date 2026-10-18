param()

$ErrorActionPreference = "Stop"
$root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$runtime = Join-Path $root "packaging\runtime"
$node = Join-Path $runtime "node-24.19.0\node.exe"
$cli = Join-Path $runtime "web-prod\node_modules\playwright-core\cli.js"
$browsers = Join-Path $runtime "playwright-browsers-1.63.0-final"

New-Item -ItemType Directory -Force -Path $browsers | Out-Null
$env:PLAYWRIGHT_BROWSERS_PATH=$browsers
$env:PLAYWRIGHT_DOWNLOAD_CONNECTION_TIMEOUT="120000"

& $node $cli install ffmpeg
if($LASTEXITCODE -ne 0){ exit $LASTEXITCODE }

$ffmpeg = Get-ChildItem -LiteralPath $browsers -Directory |
  Where-Object { $_.Name -like "ffmpeg-*" } |
  Select-Object -First 1

if(-not $ffmpeg){ throw "FFmpeg install completed without ffmpeg-* directory." }

[pscustomobject]@{
  state="PASS"
  dependency="ffmpeg"
  root=$ffmpeg.FullName
} | ConvertTo-Json

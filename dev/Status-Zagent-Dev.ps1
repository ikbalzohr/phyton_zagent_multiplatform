param()
$ErrorActionPreference = 'Stop'
if ($env:OS -ne 'Windows_NT') { throw 'Local Windows only.' }
$Root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$config = Join-Path $PSScriptRoot 'data\config\dashboard.json'
[pscustomobject]@{environment='DEVELOPMENT';dashboard_configured=(Test-Path $config);data_root=(Join-Path $PSScriptRoot 'data');status='Use authenticated dashboard status; no process-name/PID heuristics.'} | ConvertTo-Json

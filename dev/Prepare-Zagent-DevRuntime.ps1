param([string]$RuntimeSource = '', [string]$RuntimeTarget = '')
$ErrorActionPreference = 'Stop'
if ($env:OS -ne 'Windows_NT') { throw 'Local Windows only.' }
$Root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
if (-not $RuntimeSource) { $RuntimeSource = Join-Path $Root 'packaging\runtime' }
if (-not $RuntimeTarget) { $RuntimeTarget = Join-Path $PSScriptRoot 'runtime' }
if (Test-Path $RuntimeTarget) { throw 'RuntimeTarget must be fresh; old junction/hardlink overlays are not reused.' }
$required = @('files-python-3.11.9','tunnel-python-3.11.9','arcmap-python-3.11.9','node-24.19.0','playwright-browsers-1.63.0-final')
foreach ($name in $required) {
    $source = Join-Path $RuntimeSource $name
    if (-not (Test-Path $source -PathType Container)) { throw "Missing runtime: $source" }
    if (Get-ChildItem $source -Recurse -Force | Where-Object { $_.Attributes -band [IO.FileAttributes]::ReparsePoint }) { throw "Reparse points not allowed: $source" }
}
New-Item -ItemType Directory -Path $RuntimeTarget | Out-Null
foreach ($name in $required) { Copy-Item -LiteralPath (Join-Path $RuntimeSource $name) -Destination $RuntimeTarget -Recurse }
foreach ($agent in @('files','tunnel','arcmap')) {
    $target = Join-Path $RuntimeTarget "$agent-python-3.11.9"
    @('python311.zip','.','Lib\site-packages',(Join-Path $Root "agents\$agent\engine"),'import site') | Set-Content (Join-Path $target 'python311._pth') -Encoding ASCII
}
[pscustomobject]@{files_python=(Join-Path $RuntimeTarget 'files-python-3.11.9\python.exe');tunnel_python=(Join-Path $RuntimeTarget 'tunnel-python-3.11.9\python.exe');arcmap_python=(Join-Path $RuntimeTarget 'arcmap-python-3.11.9\python.exe');web_node=(Join-Path $RuntimeTarget 'node-24.19.0\node.exe')} | ConvertTo-Json -Compress

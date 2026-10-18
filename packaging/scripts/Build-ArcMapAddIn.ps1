param([string]$OutputRoot, [string]$AddInSource = "")
$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
if ($env:OS -ne 'Windows_NT') { throw 'Local Windows only.' }
$source = if ($AddInSource) { (Resolve-Path $AddInSource).Path } else { Join-Path $root 'agents\arcmap\addin' }
$config = [xml](Get-Content (Join-Path $source 'config.xml') -Raw)
$implementation = $config.SelectSingleNode('//*[local-name()="AddIn"]').GetAttribute('library')
if (-not $implementation -or [IO.Path]::GetFileName($implementation) -ne $implementation -or -not (Test-Path (Join-Path $source ('Install\'+$implementation)) -PathType Leaf)) {
    throw 'External AddIn Install/library implementation missing. A descriptor-only ZIP is not a working AddIn.'
}
if (-not $OutputRoot) { $OutputRoot = Join-Path $root 'agents\arcmap\artifacts' }
New-Item -ItemType Directory -Force $OutputRoot | Out-Null
Add-Type -AssemblyName System.IO.Compression.FileSystem
$target = Join-Path $OutputRoot 'Zagent.ArcMap.esriaddin'
$temp = $target + '.tmp'
if ((Test-Path $temp) -or (Test-Path $target)) { throw 'AddIn output must be fresh.' }
[IO.Compression.ZipFile]::CreateFromDirectory($source, $temp)
Move-Item $temp $target -Force
Get-FileHash $target -Algorithm SHA256 | Select-Object Path,Hash

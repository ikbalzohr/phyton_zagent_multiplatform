param([string]$OutputRoot, [string]$AddInSource = "", [switch]$Overwrite)
$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
if ([Environment]::OSVersion.Platform -ne [PlatformID]::Win32NT) { throw 'Local Windows only.' }
$source = if ($AddInSource) { (Resolve-Path $AddInSource).Path } else { Join-Path $root 'agents\arcmap\addin' }
$config = [xml](Get-Content (Join-Path $source 'config.xml') -Raw)
$implementation = $config.SelectSingleNode('//*[local-name()="AddIn"]').GetAttribute('library')
if (-not $implementation -or [IO.Path]::GetFileName($implementation) -ne $implementation -or -not (Test-Path (Join-Path $source ('Install\'+$implementation)) -PathType Leaf)) {
    throw 'External AddIn Install/library implementation missing. A descriptor-only ZIP is not a working AddIn.'
}
if (-not $OutputRoot) { $OutputRoot = Join-Path $root 'agents\arcmap\artifacts' }
New-Item -ItemType Directory -Force $OutputRoot | Out-Null
Add-Type -AssemblyName System.IO.Compression
Add-Type -AssemblyName System.IO.Compression.FileSystem
$target = Join-Path $OutputRoot 'Zagent.MultiPlatform.ArcMap.esriaddin'
$temp = $target + '.tmp'
if (Test-Path $temp) { throw 'AddIn temporary output must be fresh.' }
if (Test-Path $target) {
    if (-not $Overwrite) { throw 'AddIn target exists. Pass -Overwrite to rebuild.' }
    Remove-Item -LiteralPath $target -Force
}
$archive = [IO.Compression.ZipFile]::Open($temp, [IO.Compression.ZipArchiveMode]::Create)
try {
    foreach ($item in Get-ChildItem -LiteralPath $source -File -Recurse) {
        $relative = $item.FullName.Substring($source.Length).TrimStart([char]'\', [char]'/')
        $entry = $relative.Replace('\', '/')
        [IO.Compression.ZipFileExtensions]::CreateEntryFromFile(
            $archive,
            $item.FullName,
            $entry,
            [IO.Compression.CompressionLevel]::Optimal) | Out-Null
    }
}
finally { $archive.Dispose() }
Move-Item $temp $target -Force
Get-FileHash $target -Algorithm SHA256 | Select-Object Path,Hash

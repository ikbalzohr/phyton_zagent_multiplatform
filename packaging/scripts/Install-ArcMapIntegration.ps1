[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][string]$InstallRoot,
    [switch]$RetireProduction,
    [switch]$ValidateOnly
)
$ErrorActionPreference = 'Stop'
if (-not [Environment]::OSVersion.Platform.ToString().StartsWith('Win')) { throw 'Windows owner desktop is required.' }

$root = (Resolve-Path -LiteralPath $InstallRoot).Path.TrimEnd('\')
$engine = Join-Path $root 'agents\arcmap\engine'
$toolbox = Join-Path $engine 'arcmap_bridge\ArcMapAgent.pyt'
$bundle = Join-Path $root 'agents\arcmap\artifacts\Zagent.MultiPlatform.ArcMap.esriaddin'
$bridgeLocator = Join-Path $engine 'arcmap_bridge\bridge_runtime.json'
$data = Join-Path $root 'data\arcmap'
$legacyGuid = '{B88AE9DB-CC43-4EA0-8B91-A72FC933D690}'
$newGuid = '{6A9B7E2C-541F-4693-AB20-78D6E2C02111}'
$newName = 'Zagent Multi Platform ArcMap'

foreach ($required in @($toolbox, (Join-Path $engine 'arcmap_bridge\bootstrap.py'), $bundle)) {
    if (-not (Test-Path -LiteralPath $required -PathType Leaf)) { throw "Missing ArcMap integration file: $required" }
}
Add-Type -AssemblyName System.IO.Compression.FileSystem

function Get-AddInManifest([string]$path) {
    $archive = [IO.Compression.ZipFile]::OpenRead($path)
    try {
        $config = $archive.GetEntry('config.xml')
        if ($null -eq $config) { throw 'Add-In package missing config.xml' }
        $sr = [IO.StreamReader]::new($config.Open())
        try { [xml]$doc = $sr.ReadToEnd() } finally { $sr.Dispose() }
        $idNode = $doc.SelectSingleNode('//*[local-name()="AddInID"]')
        $nameNode = $doc.SelectSingleNode('//*[local-name()="Name"]')
        $addin = $doc.SelectSingleNode('//*[local-name()="AddIn"]')
        $extension = $doc.SelectSingleNode('//*[local-name()="Extension"]')
        return @{
            Id = if ($idNode) { $idNode.InnerText } else { '' }
            Name = if ($nameNode) { $nameNode.InnerText } else { '' }
            AutoLoad = if ($extension) { $extension.GetAttribute('autoLoad') } else { '' }
            Library = if ($addin) { $addin.GetAttribute('library') } else { '' }
            HasImplementation = ($null -ne $archive.GetEntry('Install/zagent_arcmap_addin.py'))
            HasToolboxProxy = ($null -ne $archive.GetEntry('Install/ZagentMultiPlatformToolbox.pyt'))
        }
    } finally { $archive.Dispose() }
}

$manifest = Get-AddInManifest $bundle
if ($manifest.Id -ne $newGuid -or $manifest.Name -ne $newName -or
    $manifest.AutoLoad -ne 'true' -or $manifest.Library -ne 'zagent_arcmap_addin.py' -or
    -not $manifest.HasImplementation -or -not $manifest.HasToolboxProxy) {
    throw ('Multi Platform .esriaddin validation failed: ' + ($manifest | ConvertTo-Json -Compress))
}

$documents = [Environment]::GetFolderPath([Environment+SpecialFolder]::MyDocuments)
$local = [Environment]::GetFolderPath([Environment+SpecialFolder]::LocalApplicationData)
if ([string]::IsNullOrWhiteSpace($documents) -or [string]::IsNullOrWhiteSpace($local)) {
    throw 'The interactive Windows owner profile is required.'
}
$addinRoot = Join-Path $documents 'ArcGIS\AddIns\Desktop10.6'
$installedDir = Join-Path $addinRoot $newGuid
$installedBundle = Join-Path $installedDir 'Zagent.MultiPlatform.ArcMap.esriaddin'
$ownerDir = Join-Path $local 'Zagent\ArcMap'
$ownerLocator = Join-Path $ownerDir 'multi-platform.json'
$toolboxInstalled = Join-Path $documents 'ArcGIS\Toolboxes\Zagent Multi Platform.pyt'
$backupBase = Join-Path $ownerDir 'integration-backups'

$result = @{
    ok = $true
    validated = $true
    installed = $false
    install_root = $root
    addin_bundle = $bundle
    addin_target = $installedBundle
    locator = $ownerLocator
    toolbox = $toolboxInstalled
    retire_production = [bool]$RetireProduction
    legacy_retired_count = 0
}
if ($ValidateOnly) {
    $result | ConvertTo-Json -Depth 5
    return
}
if (@(Get-Process -Name ArcMap -ErrorAction SilentlyContinue).Count -gt 0) {
    throw 'Close ArcMap Desktop before installing the Add-In. The installed ArcMap session will not be terminated.'
}

foreach ($folder in @($installedDir, $ownerDir, (Split-Path -Parent $toolboxInstalled), $backupBase)) {
    [IO.Directory]::CreateDirectory($folder) | Out-Null
}
$stamp = (Get-Date -Format 'yyyyMMdd_HHmmss_fff')
$backupDir = Join-Path $backupBase $stamp
[IO.Directory]::CreateDirectory($backupDir) | Out-Null

if (Test-Path -LiteralPath $installedBundle -PathType Leaf) {
    $existingManifest = Get-AddInManifest $installedBundle
    if ($existingManifest.Id -ne $newGuid) { throw 'Refusing to overwrite an unrelated Add-In.' }
    Copy-Item -LiteralPath $installedBundle -Destination (Join-Path $backupDir 'previous-multi-platform.esriaddin')
}
foreach ($entry in @(
    @{Target=$ownerLocator;Name='previous-multi-platform-locator.json'},
    @{Target=$bridgeLocator;Name='previous-bridge-runtime.json'},
    @{Target=$toolboxInstalled;Name='previous-toolbox.pyt'}
)) {
    if (Test-Path -LiteralPath $entry.Target -PathType Leaf) {
        Copy-Item -LiteralPath $entry.Target -Destination (Join-Path $backupDir $entry.Name)
    }
}
$stagedAddin = $installedBundle + '.new'
Copy-Item -LiteralPath $bundle -Destination $stagedAddin -Force
Move-Item -LiteralPath $stagedAddin -Destination $installedBundle -Force

$runtime = @{
    schema_version = '1.0'
    environment = 'MULTI_PLATFORM'
    data_root = $data
    config_dir = (Join-Path $data 'config')
    ipc_root = (Join-Path $data 'ipc')
    generated_by = 'Zagent Multi Platform Add-In installer'
}
$ownerConfig = @{
    environment = 'MULTI_PLATFORM'
    engine_root = $engine
    data_root = $data
    config_dir = (Join-Path $data 'config')
    ipc_root = (Join-Path $data 'ipc')
}
foreach ($directory in @($data, (Join-Path $data 'config'), (Join-Path $data 'ipc'))) {
    [IO.Directory]::CreateDirectory($directory) | Out-Null
}
$utf8 = [Text.UTF8Encoding]::new($false)
function Set-AtomicJson([string]$path, [object]$data) {
    $tmp = $path + '.new'
    [IO.File]::WriteAllText($tmp, ($data | ConvertTo-Json -Depth 6), $utf8)
    Move-Item -LiteralPath $tmp -Destination $path -Force
}
Set-AtomicJson $bridgeLocator $runtime
Set-AtomicJson $ownerLocator $ownerConfig

$archive = [IO.Compression.ZipFile]::OpenRead($bundle)
try {
    $entry = $archive.GetEntry('Install/ZagentMultiPlatformToolbox.pyt')
    $src = $entry.Open()
    try {
        $dst = [IO.File]::Create($toolboxInstalled + '.new')
        try { $src.CopyTo($dst) } finally { $dst.Dispose() }
    } finally { $src.Dispose() }
    Move-Item -LiteralPath ($toolboxInstalled + '.new') -Destination $toolboxInstalled -Force
} finally { $archive.Dispose() }

if ($RetireProduction -and (Test-Path -LiteralPath $addinRoot -PathType Container)) {
    $legacyFiles = @(Get-ChildItem -LiteralPath $addinRoot -Filter '*.esriaddin' -Recurse -File -ErrorAction SilentlyContinue)
    $count = 0
    foreach ($old in $legacyFiles) {
        if ($old.FullName -eq $installedBundle) { continue }
        try { $oldManifest = Get-AddInManifest $old.FullName } catch { continue }
        if ($oldManifest.Id -ne $legacyGuid -or $oldManifest.Name -ne 'Zagent ArcMap') { continue }
        $dest = Join-Path $backupDir ('retired-production-' + $count + '.esriaddin')
        Move-Item -LiteralPath $old.FullName -Destination $dest
        $count++
    }
    $result.legacy_retired_count = $count
}
$result.installed = $true
$result.backup_dir = $backupDir
$result | ConvertTo-Json -Depth 5

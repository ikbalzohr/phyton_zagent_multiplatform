[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][string]$PythonHome,
    [Parameter(Mandatory=$true)][string]$SitePackages,
    [Parameter(Mandatory=$true)][string]$OutputRoot,
    [Parameter(Mandatory=$true)][string]$QgisEngine
)
$ErrorActionPreference = 'Stop'

# Produce a Python 3.12 runtime independent of the donor clone / venv.
# This is a developer packaging step. Core will never run this script.
$PythonHome = (Resolve-Path -LiteralPath $PythonHome).Path
$SitePackages = (Resolve-Path -LiteralPath $SitePackages).Path
$QgisEngine = (Resolve-Path -LiteralPath $QgisEngine).Path
$OutputRoot = [IO.Path]::GetFullPath($OutputRoot)
if (Test-Path -LiteralPath $OutputRoot) {
    throw "Refusing to overwrite an existing QGIS runtime."
}
if (-not (Test-Path -LiteralPath (Join-Path $QgisEngine 'src\qgis_mcp\server.py'))) {
    throw "Bundled QGIS engine is missing."
}
foreach ($f in @('python.exe', 'python312.dll', 'Lib\os.py')) {
    if (-not (Test-Path -LiteralPath (Join-Path $PythonHome $f) -PathType Leaf)) {
        throw "Python 3.12 runtime component is missing: $f"
    }
}
foreach ($dir in @('mcp', 'pydantic')) {
    if (-not (Test-Path -LiteralPath (Join-Path $SitePackages $dir) -PathType Container)) {
        throw "QGIS dependency folder is missing: $dir"
    }
}
$parent = [IO.Path]::GetDirectoryName($OutputRoot)
[IO.Directory]::CreateDirectory($parent) | Out-Null
$staging = $OutputRoot + '.prepare-' + [Guid]::NewGuid().ToString('N')
New-Item -ItemType Directory -Path $staging -ErrorAction Stop | Out-Null
try {
    Get-ChildItem -LiteralPath $PythonHome -Force | ForEach-Object {
        Copy-Item -LiteralPath $_.FullName -Destination $staging -Recurse -Force
    }
    $targetSite = Join-Path $staging 'Lib\site-packages'
    [IO.Directory]::CreateDirectory($targetSite) | Out-Null
    Get-ChildItem -LiteralPath $SitePackages -Force | ForEach-Object {
        Copy-Item -LiteralPath $_.FullName -Destination $targetSite -Recurse -Force
    }

    # The development venv contains an editable .pth with an absolute
    # qgis-mcp source path. Remove it: source is in this product's engine.
    Get-ChildItem -LiteralPath $targetSite -File -Filter '*.pth' | ForEach-Object {
        if ($_.Name.StartsWith('_editable', [StringComparison]::OrdinalIgnoreCase) -or
            $_.Name.StartsWith('__editable', [StringComparison]::OrdinalIgnoreCase)) {
            Remove-Item -LiteralPath $_.FullName -Force
        } else {
            $content = [IO.File]::ReadAllText($_.FullName)
            if ($content -match '(?i)[a-z]:\\' -or $content -match '(?i)/home/|/users/') {
                throw "Absolute developer path remains inside a Python .pth file."
            }
        }
    }
    Get-ChildItem -LiteralPath $targetSite -Directory -Filter 'qgis_mcp*.dist-info' | ForEach-Object {
        $direct = Join-Path $_.FullName 'direct_url.json'
        if (Test-Path -LiteralPath $direct) { Remove-Item -LiteralPath $direct -Force }
    }

    @(
        'python312.zip',
        '.',
        'Lib',
        'DLLs',
        'Lib\site-packages',
        '..\..\engine\src',
        'import site'
    ) | Set-Content -LiteralPath (Join-Path $staging 'python312._pth') -Encoding ASCII

    $py = Join-Path $staging 'python.exe'
    & $py -c 'import sys; import qgis_mcp.server; assert sys.version_info[:2] == (3,12); print(12345)'
    if ($LASTEXITCODE -ne 0) { throw "Isolated QGIS runtime smoke failed." }

    [IO.Directory]::Move($staging, $OutputRoot)
    $resultPy = Join-Path $OutputRoot 'python.exe'
    & $resultPy -c 'import qgis_mcp.server; print(67890)'
    if ($LASTEXITCODE -ne 0) { throw "Relocated QGIS Python cannot import product engine." }
    Write-Output ("QGIS_RUNTIME_READY " + $OutputRoot)
}
finally {
    if (Test-Path -LiteralPath $staging) {
        Remove-Item -LiteralPath $staging -Recurse -Force
    }
}
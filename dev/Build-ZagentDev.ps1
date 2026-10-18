param([string]$Dotnet = 'dotnet', [switch]$SkipWeb)
$ErrorActionPreference = 'Stop'
$Root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
. (Join-Path $Root 'packaging\scripts\Build-Common.ps1')
$sdk = Initialize-ZagentBuild -Root $Root -Dotnet $Dotnet
& $sdk build (Join-Path $Root 'Zagent.slnx') -c Debug --nologo
if ($LASTEXITCODE -ne 0) { throw 'DEV .NET build failed.' }
if (-not $SkipWeb) {
    Push-Location (Join-Path $Root 'agents\web\engine')
    try {
        & npm run build
        if ($LASTEXITCODE -ne 0) { throw 'DEV Web build failed; provision locked node_modules explicitly first.' }
    } finally { Pop-Location }
}

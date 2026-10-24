[CmdletBinding()]
param([Parameter(Mandatory=$true)][string]$InstallRoot)
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'WindowsDashboard-Provisioning.ps1')
Assert-ZagentOwnerConsole
$InstallRoot = (Resolve-Path -LiteralPath $InstallRoot).Path
Assert-ZagentPlainPath $InstallRoot
$Python = Join-Path $env:LOCALAPPDATA 'Zagent-Envs\files\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $Python -PathType Leaf)) { throw 'Verified Files venv missing.' }
foreach ($name in @('Owner-PrivateConfig.ps1','Enable-OwnerFilesCapabilities.ps1','Test-OwnerFilesCapabilities.ps1')) {
    $tokens = $null; $parseErrors = $null
    $null = [Management.Automation.Language.Parser]::ParseFile((Join-Path $PSScriptRoot $name), [ref]$tokens, [ref]$parseErrors)
    if (@($parseErrors).Count -gt 0) { $parseErrors | ForEach-Object { Write-Host $_.Message }; throw ('PowerShell parsing failed: ' + $name) }
}
Write-Host 'PowerShell parser checks passed. Running disposable Windows fixtures; owner DataRoot is not used.'
& $Python (Join-Path $PSScriptRoot 'windows_files_security_checks.py')
if ($LASTEXITCODE -ne 0) { throw 'Focused Windows Files checks failed; preserve output, do not activate broader capabilities.' }
Write-Host 'No grants/profile approval/OAuth tokens/production processes changed by this validation helper.'

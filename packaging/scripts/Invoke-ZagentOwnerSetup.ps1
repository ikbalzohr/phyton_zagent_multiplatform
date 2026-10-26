[CmdletBinding()]
param(
    [ValidateSet('Validate','ApplyCapability','ApplyCapabilityAndStart')][string]$Mode = 'Validate',
    [string]$InstallRoot = '',
    [string]$DataRoot = '',
    [string]$OwnerPrincipal = '',
    [string]$WorkspaceId = '',
    [string]$DeviceId = '',
    [string]$InstallationId = '',
    [string]$CoreExecutable = '',
    [string]$CoreSha256 = '',
    [string]$DotnetRoot = '',
    [string]$FilesPython = '',
    [string]$TunnelPython = ''
)
# Owner-console entry for an ALREADY DEPLOYED, enrolled Windows installation.
# No build/install, enrollment, migration, consent, renewal, or command-policy changes.
# Noninteractive means no prompts; the reviewed launcher still requires an owner console.
$ErrorActionPreference = 'Stop'
if ($env:OS -ne 'Windows_NT') { throw 'Windows owner setup required; no changes performed.' }
foreach ($value in @($InstallRoot,$DataRoot,$OwnerPrincipal,$WorkspaceId,$DeviceId,$InstallationId,
                    $CoreExecutable,$CoreSha256,$DotnetRoot,$FilesPython,$TunnelPython)) {
    if ([string]::IsNullOrWhiteSpace($value)) { throw 'All deployment inputs are explicit and required; no discovery or prompts.' }
}
if ($CoreSha256 -cnotmatch '\A[0-9a-fA-F]{64}\z') { throw 'Reviewed deployed Core SHA256 required; not a source revision or placeholder.' }
foreach ($name in @('WindowsDashboard-Provisioning.ps1','Owner-PrivateConfig.ps1',
                    'ProfileAdministrationBootstrap.ps1','Enable-OwnerProfileAdministration.ps1','Start-OwnerCore.ps1')) {
    $helper = Join-Path $PSScriptRoot $name
    if (-not (Test-Path -LiteralPath $helper -PathType Leaf)) { throw 'Reviewed setup helper missing.' }
    if ((Get-Item -LiteralPath $helper -Force).Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Reparse helper rejected.' }
}
. (Join-Path $PSScriptRoot 'WindowsDashboard-Provisioning.ps1')
Assert-ZagentOwnerConsole
Assert-ZagentPlainPath $PSScriptRoot
foreach ($name in @('WindowsDashboard-Provisioning.ps1','Owner-PrivateConfig.ps1',
                    'ProfileAdministrationBootstrap.ps1','Enable-OwnerProfileAdministration.ps1','Start-OwnerCore.ps1')) {
    $helper = Join-Path $PSScriptRoot $name
    Assert-ZagentPlainPath $helper
}
. (Join-Path $PSScriptRoot 'Owner-PrivateConfig.ps1')
. (Join-Path $PSScriptRoot 'ProfileAdministrationBootstrap.ps1')
$enableHelper = Join-Path $PSScriptRoot 'Enable-OwnerProfileAdministration.ps1'
$startHelper = Join-Path $PSScriptRoot 'Start-OwnerCore.ps1'

# Resolve every launch prerequisite BEFORE the capability helper can write.
foreach ($name in @('InstallRoot','DataRoot','DotnetRoot','CoreExecutable','FilesPython','TunnelPython')) {
    $value = Get-Variable -Name $name -ValueOnly
    if ($value -cnotmatch '\A[A-Za-z]:\\' -or -not (Test-Path -LiteralPath $value)) { throw 'Existing absolute local deployment path required.' }
    Assert-ZagentPlainPath $value
    Set-Variable -Name $name -Value ((Resolve-Path -LiteralPath $value).Path.TrimEnd('\'))
}
foreach ($directory in @($InstallRoot,$DataRoot,$DotnetRoot)) {
    if (-not (Test-Path -LiteralPath $directory -PathType Container)) { throw 'Deployment directory required.' }
}
if (-not $CoreExecutable.StartsWith(($InstallRoot + '\'), [StringComparison]::OrdinalIgnoreCase) -or
    [IO.Path]::GetFileName($CoreExecutable) -ine 'Zagent.Core.exe') { throw 'Explicit Core apphost inside InstallRoot required.' }
foreach ($file in @($CoreExecutable,$FilesPython,$TunnelPython,(Join-Path $DotnetRoot 'dotnet.exe'),
                    (Join-Path $InstallRoot 'agents\web\engine\dist\index.js'))) {
    if (-not (Test-Path -LiteralPath $file -PathType Leaf)) { throw 'Existing deployed runtime/build prerequisite missing; no automatic install.' }
    Assert-ZagentPlainPath $file
}
foreach ($python in @($FilesPython,$TunnelPython)) {
    if ([IO.Path]::GetFileName($python) -ine 'python.exe') { throw 'Explicit component python.exe required; no PATH fallback.' }
}
if ((Get-FileHash -LiteralPath $CoreExecutable -Algorithm SHA256).Hash -ine $CoreSha256) { throw 'Deployed Core hash mismatch; deployment NOT_PERFORMED.' }
Assert-ZagentOwnerAcl $DataRoot
$data = $DataRoot # Reviewed private-path utilities bind to this protected anchor.
foreach ($file in @('config\dashboard.json','config\internal-secrets.dpapi.json')) {
    $path = Join-Path $data $file
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { throw 'Existing enrollment missing; never reprovision automatically.' }
    # ACL/path metadata ONLY: do not read dashboard credentials or DPAPI ciphertext.
    Assert-ZagentPlainPath $path
    Assert-ZagentOwnerAcl $path
}
Assert-ProfileAdminCoreStopped
$machinePath = Join-Path $data 'config\zagent.machine.json'
$machineBytes = Read-BoundedBytes $machinePath
$machine = (Read-StrictJson $machineBytes).Object
if ($machine.install_root -isnot [string] -or $machine.data_root -isnot [string] -or
    $machine.install_root.TrimEnd('\') -ine $InstallRoot -or $machine.data_root.TrimEnd('\') -ine $data) {
    throw 'Existing enrolled install/DataRoot mismatch.'
}
$target = Join-Path $data 'tunnel\config\tunnel.json'
$before = Read-BoundedBytes $target
$next = New-ProfileAdministrationPlan $before $OwnerPrincipal $WorkspaceId $DeviceId $InstallationId
$needsChange = [Convert]::ToBase64String($before) -cne [Convert]::ToBase64String($next)
Assert-SnapshotUnchanged $machinePath $machineBytes
Assert-SnapshotUnchanged $target $before
Assert-ProfileAdminCoreStopped
if ($Mode -ceq 'Validate') {
    Write-Output ([pscustomobject]@{ status='OWNER_SETUP_PREFLIGHT_ONLY'; capability_change_needed=$needsChange;
        deployment='DEPLOYMENT_NOT_PERFORMED'; migration='MIGRATION_NOT_APPLIED'; core='NOT_STARTED' })
    return
}
# Reuse the single-file backup/CAS/readback helper; never edit profiles or static bindings.
# No rollback on later startup failure: retain verified capability and its private backup.
& $enableHelper -InstallRoot $InstallRoot -DataRoot $data -OwnerPrincipal $OwnerPrincipal `
    -WorkspaceId $WorkspaceId -DeviceId $DeviceId -InstallationId $InstallationId
# Independent authority readback: the planner must now produce byte-identical output.
Assert-ProfileAdminCoreStopped
Assert-SnapshotUnchanged $machinePath $machineBytes
$after = Read-BoundedBytes $target
$checked = New-ProfileAdministrationPlan $after $OwnerPrincipal $WorkspaceId $DeviceId $InstallationId
if ([Convert]::ToBase64String($after) -cne [Convert]::ToBase64String($checked)) { throw 'Capability readback is not current; Core NOT_STARTED.' }
Write-Output ([pscustomobject]@{ status='OWNER_SETUP_CAPABILITY_VERIFIED'; deployment='DEPLOYMENT_NOT_PERFORMED';
    migration='MIGRATION_NOT_APPLIED'; core='NOT_STARTED'; live_readiness='NOT_VERIFIED' })
if ($Mode -ceq 'ApplyCapability') { return }
# Core exclusively owns all child lifecycles. Launcher runs synchronously in this console.
# This is NOT a health check; it returns only when Core exits. Never launch standalone Files.
Assert-SnapshotUnchanged $target $after
Assert-SnapshotUnchanged $machinePath $machineBytes
Assert-ProfileAdminCoreStopped
if ((Get-FileHash -LiteralPath $CoreExecutable -Algorithm SHA256).Hash -ine $CoreSha256) { throw 'Core changed after preflight; no launch.' }
$previousFiles = $env:ZAGENT_FILES_PYTHON
$previousTunnel = $env:ZAGENT_TUNNEL_PYTHON
try {
    $env:ZAGENT_FILES_PYTHON = $FilesPython
    $env:ZAGENT_TUNNEL_PYTHON = $TunnelPython
    & $startHelper -InstallRoot $InstallRoot -DataRoot $data -DotnetRoot $DotnetRoot -CoreExecutable $CoreExecutable
}
finally {
    $env:ZAGENT_FILES_PYTHON = $previousFiles
    $env:ZAGENT_TUNNEL_PYTHON = $previousTunnel
}

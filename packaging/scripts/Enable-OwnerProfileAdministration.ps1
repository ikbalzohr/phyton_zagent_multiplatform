[CmdletBinding()]
param(
    [string]$InstallRoot,
    [string]$DataRoot,
    [string]$OwnerPrincipal,
    [string]$WorkspaceId,
    [string]$DeviceId,
    [string]$InstallationId
)
# Owner-local deployment only; never invoke via public Files shell tools.
# Capability-only: ONE tunnel.json replacement. profiles.json is initialized later by Files.
$ErrorActionPreference = 'Stop'
foreach ($inputValue in @($InstallRoot,$DataRoot,$OwnerPrincipal,$WorkspaceId,$DeviceId,$InstallationId)) {
    if ([string]::IsNullOrWhiteSpace($inputValue)) { throw 'All six explicit deployment inputs are required; no interactive input is requested.' }
}
. (Join-Path $PSScriptRoot 'WindowsDashboard-Provisioning.ps1')
. (Join-Path $PSScriptRoot 'Owner-PrivateConfig.ps1')
. (Join-Path $PSScriptRoot 'ProfileAdministrationBootstrap.ps1')
if ($env:OS -ne 'Windows_NT') { throw 'Windows owner deployment required.' }
$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
if ($identity.IsSystem -or $identity.IsAnonymous -or $null -eq $identity.User) { throw 'Existing enrolled Windows owner SID required.' }
foreach ($path in @($InstallRoot,$DataRoot)) {
    if ($path -cnotmatch '\A[A-Za-z]:\\' -or -not (Test-Path -LiteralPath $path -PathType Container)) { throw 'Existing absolute local directory required.' }
    Assert-ZagentPlainPath $path
}
$InstallRoot = (Resolve-Path -LiteralPath $InstallRoot).Path.TrimEnd('\')
$data = (Resolve-Path -LiteralPath $DataRoot).Path.TrimEnd('\')
Assert-ZagentOwnerAcl $data
Assert-ProfileAdminCoreStopped
$machinePath = Join-Path $data 'config\zagent.machine.json'
$machineBytes = Read-BoundedBytes $machinePath
$machine = (Read-StrictJson $machineBytes).Object
if ($machine.install_root.TrimEnd('\') -ine $InstallRoot -or $machine.data_root.TrimEnd('\') -ine $data) { throw 'Existing enrolled install/DataRoot mismatch.' }
$target = Join-Path $data 'tunnel\config\tunnel.json'
$before = Read-BoundedBytes $target
$next = New-ProfileAdministrationPlan $before $OwnerPrincipal $WorkspaceId $DeviceId $InstallationId
if ([Convert]::ToBase64String($before) -ceq [Convert]::ToBase64String($next)) {
    Assert-ProfileAdminCoreStopped; Assert-SnapshotUnchanged $machinePath $machineBytes; Assert-SnapshotUnchanged $target $before
    Write-Output 'PROFILE_ADMIN_ALREADY_CURRENT; no writes; Core not started.'; return
}
$tag = [guid]::NewGuid().ToString('N'); $candidate = $target + '.' + $tag + '.tmp'; $backup = $target + '.' + $tag + '.bak'
foreach ($artifact in @(@{Path=$candidate;Bytes=$next},@{Path=$backup;Bytes=$before})) {
    Assert-ProfileAdminCoreStopped
    Assert-MigrationPrivatePath ([IO.Path]::GetDirectoryName($artifact.Path)); Assert-ZagentPlainPath $artifact.Path
    $stream = [IO.File]::Open($artifact.Path,[IO.FileMode]::CreateNew,[IO.FileAccess]::Write,[IO.FileShare]::None)
    try { $stream.Write($artifact.Bytes,0,$artifact.Bytes.Length); $stream.Flush($true) } finally { $stream.Dispose() }
    Set-ZagentOwnerAcl $artifact.Path
    Assert-SnapshotUnchanged $artifact.Path $artifact.Bytes
}
# Re-evaluate expiry and every plan assertion immediately before a single-file publish.
Assert-ProfileAdminCoreStopped
Assert-SnapshotUnchanged $machinePath $machineBytes
Assert-SnapshotUnchanged $target $before
Assert-SnapshotUnchanged $backup $before
Assert-SnapshotUnchanged $candidate $next
$rechecked = New-ProfileAdministrationPlan $before $OwnerPrincipal $WorkspaceId $DeviceId $InstallationId
if ([Convert]::ToBase64String($next) -cne [Convert]::ToBase64String($rechecked)) { throw 'Capability plan changed before publish.' }
Assert-ProfileAdminCoreStopped
# PowerShell binds $null to an empty string for this .NET string parameter.
# NullString passes a real null; the verified independent backup already exists.
[IO.File]::Replace($candidate,$target,[System.Management.Automation.Language.NullString]::Value,$false)
Assert-MigrationPrivatePath $target
Assert-SnapshotUnchanged $target $next
Assert-SnapshotUnchanged $backup $before
Write-Output ('PROFILE_ADMIN_CAPABILITY_APPLIED; exact readback verified; private backup=' + $backup + '; Core NOT_STARTED. No profile, command policy, OAuth, scope, expiry or revocation mutation.')

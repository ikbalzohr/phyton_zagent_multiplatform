# Rebind exactly ONE existing owner command policy entry to the approved agentRoot profile.
# Noninteractive by design: no consent prompt, no per-operation approval, no OAuth action, no Core start.
# Reads files\config\remote_execution_policy.json (v1 or v2) and files\config\profiles.json;
# writes ONLY remote_execution_policy.json. expires_at/revocation/scopes/tools/tool_policy/limits and
# every unrelated configuration byte are preserved and proven byte-for-byte (see plan lib).
[CmdletBinding(DefaultParameterSetName='Apply')]
param(
    [Parameter(Mandatory=$true)][string]$InstallRoot,
    [Parameter(Mandatory=$true)][string]$DataRoot,
    [Parameter(Mandatory=$true,ParameterSetName='Apply')][string]$SourceProfileId,
    [Parameter(Mandatory=$true,ParameterSetName='Apply')][string]$SourceRoot,
    [Parameter(ParameterSetName='Apply')][switch]$AllowRemovedSourceProfile,
    [Parameter(Mandatory=$true,ParameterSetName='Inspect')][switch]$InspectOnly
)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
. (Join-Path $PSScriptRoot 'WindowsDashboard-Provisioning.ps1')
. (Join-Path $PSScriptRoot 'Owner-PrivateConfig.ps1')
. (Join-Path $PSScriptRoot 'Owner-CommandPolicyRebind.ps1')
. (Join-Path $PSScriptRoot 'ProfileAdministrationBootstrap.ps1')
Assert-ZagentOwnerConsole
$InstallRoot = (Resolve-Path -LiteralPath $InstallRoot).Path.TrimEnd('\')
$data = (Resolve-Path -LiteralPath $DataRoot).Path.TrimEnd('\')
Assert-ZagentPlainPath $InstallRoot
Assert-ZagentOwnerAcl $data
if ($data -ieq $InstallRoot) { throw 'Dedicated existing enrolled DataRoot required.' }
$expectedRoot = 'D:\3-Ikbalzohr\Agent'
if (-not $InspectOnly) {
    if ([string]::IsNullOrWhiteSpace($SourceRoot)) { throw 'Explicit existing source root (current policy root) required; no default.' }
    if ($SourceProfileId -cnotmatch '\A[A-Za-z0-9_-]{1,256}\z') { throw 'Explicit bounded source profile identifier required; no trim or repair.' }
}
Assert-ProfileAdminCoreStopped
$machinePath = Join-Path $data 'config\zagent.machine.json'
$machineBytes = Read-BoundedBytes $machinePath
$machine = (Read-StrictJson $machineBytes).Object
if ($machine.install_root -isnot [string] -or $machine.data_root -isnot [string] -or
    $machine.install_root.TrimEnd('\') -ine $InstallRoot -or $machine.data_root.TrimEnd('\') -ine $data) { throw 'Existing enrolled install/DataRoot mismatch.' }
$policyPath = Join-Path $data 'files\config\remote_execution_policy.json'
$profilesPath = Join-Path $data 'files\config\profiles.json'
Assert-ZagentPlainPath $policyPath
Assert-ZagentPlainPath $profilesPath
Assert-MigrationPrivatePath ([IO.Path]::GetDirectoryName($policyPath))
Assert-MigrationPrivatePath ([IO.Path]::GetDirectoryName($profilesPath))
$beforePolicy = Read-BoundedBytes $policyPath
$beforeProfiles = Read-BoundedBytes $profilesPath
Assert-ProfileAdminCoreStopped
if ($InspectOnly) {
    $summary=@(Get-OwnerCommandPolicySummary $beforePolicy)
    Assert-SnapshotUnchanged $machinePath $machineBytes
    Assert-SnapshotUnchanged $profilesPath $beforeProfiles
    Assert-SnapshotUnchanged $policyPath $beforePolicy
    Write-Output (ConvertTo-Json -Depth 8 -InputObject @{ status='INSPECT_ONLY'; writes=0; policies=$summary })
    return
}
$plan = New-OwnerCommandPolicyRebindPlan $beforePolicy $beforeProfiles $SourceProfileId $SourceRoot -AllowRemovedSourceProfile:$AllowRemovedSourceProfile
if ((Test-NormalizedRoot $plan.Root $expectedRoot) -eq $false) { throw 'Target agentRoot root is not the approved local placement; no write performed.' }
if ([Convert]::ToBase64String($plan.Bytes) -ceq [Convert]::ToBase64String($beforePolicy)) {
    Assert-ProfileAdminCoreStopped
    Assert-SnapshotUnchanged $policyPath $beforePolicy
    Write-Output ('PROFILE_COMMAND_POLICY_ALREADY_CURRENT; profile_id=' + $SourceProfileId + '->agentRoot; no writes; Core NOT_STARTED.')
    return
}
$tag = [guid]::NewGuid().ToString('N')
$temp = $policyPath + '.' + $tag + '.tmp'
$backup = $policyPath + '.' + $tag + '.bak'
Assert-ZagentPlainPath $temp
Assert-ZagentPlainPath $backup
if ((Test-Path -LiteralPath $temp) -or (Test-Path -LiteralPath $backup)) { throw 'Private artifact collision.' }
Assert-ProfileAdminCoreStopped
Assert-SnapshotUnchanged $policyPath $beforePolicy
Assert-SnapshotUnchanged $machinePath $machineBytes
Assert-SnapshotUnchanged $profilesPath $beforeProfiles
# Re-evaluate the plan against fresh snapshots immediately before a single-file publish.
$recheck = New-OwnerCommandPolicyRebindPlan $beforePolicy $beforeProfiles $SourceProfileId $SourceRoot -AllowRemovedSourceProfile:$AllowRemovedSourceProfile
if ([Convert]::ToBase64String($recheck.Bytes) -cne [Convert]::ToBase64String($plan.Bytes)) { throw 'Command policy plan changed before publish.' }
Assert-ProfileAdminCoreStopped
$stream = [IO.File]::Open($temp, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write, [IO.FileShare]::None)
try { $stream.Write($plan.Bytes, 0, $plan.Bytes.Length); $stream.Flush($true) } finally { $stream.Dispose() }
Set-ZagentOwnerAcl $temp
Assert-ProfileAdminCoreStopped
Assert-SnapshotUnchanged $policyPath $beforePolicy
Assert-SnapshotUnchanged $machinePath $machineBytes
Assert-SnapshotUnchanged $profilesPath $beforeProfiles
Assert-SnapshotUnchanged $temp $plan.Bytes
[IO.File]::Replace($temp, $policyPath, $backup)
Assert-MigrationPrivatePath $policyPath
Assert-MigrationPrivatePath $backup
if ([Convert]::ToBase64String((Read-BoundedBytes $backup)) -cne [Convert]::ToBase64String($beforePolicy)) { throw 'Backup mismatch; keep Core stopped.' }
if ([Convert]::ToBase64String((Read-BoundedBytes $policyPath)) -cne [Convert]::ToBase64String($plan.Bytes)) { throw 'Read-back mismatch; keep Core stopped.' }
Assert-ProfileAdminCoreStopped
Write-Output ('Private backup: ' + $backup)
Write-Output ('PROFILE_COMMAND_POLICY_REBOUND; profile_id=' + $SourceProfileId + '->agentRoot; root=' + $plan.Root + '; previous_profile_id=' + $SourceProfileId + '; exact backup/read-back verified; Core NOT_STARTED. Only files_resource-equivalent profile_id and root change. expires_at, revocation, scopes, tools, tool_policy, limits and OAuth preserved.')

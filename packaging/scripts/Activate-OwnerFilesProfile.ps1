[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][string]$InstallRoot,
    [Parameter(Mandatory=$true)][string]$DataRoot,
    [string[]]$AllowedProfileIds = @('agentRoot')
)
# OWNER LOCAL ONLY. Run in the enrolled interactive Windows owner's console.
# Public files_exec_command / MCP is NOT an administration channel for this helper.
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'WindowsDashboard-Provisioning.ps1')
. (Join-Path $PSScriptRoot 'Owner-PrivateConfig.ps1')
. (Join-Path $PSScriptRoot 'Owner-ProfileActivation.ps1')
Assert-ZagentOwnerConsole
Assert-ActivationPath $InstallRoot
Assert-ActivationPath $DataRoot
$InstallRoot = (Resolve-Path -LiteralPath $InstallRoot).Path.TrimEnd('\')
$data = (Resolve-Path -LiteralPath $DataRoot).Path.TrimEnd('\')
if ($data -ieq $InstallRoot) { throw 'Dedicated existing enrolled DataRoot required.' }
Assert-ZagentOwnerAcl $data
Assert-CoreStopped
# Validate enrollment anchors by existing owner/private ACL + non-reparse regular
# file metadata only. Never read/decrypt identity, dashboard, DPAPI or OAuth tokens.
$anchorMetadata = @{}
foreach ($name in @('dashboard.json','device_identity.json','internal-secrets.dpapi.json')) {
    $path = Join-Path $data ('config\' + $name)
    Assert-MigrationPrivatePath $path
    $item = Get-Item -LiteralPath $path -Force
    if ($item.PSIsContainer -or $item.Length -lt 2 -or $item.Length -gt 1048576) { throw 'Existing enrollment anchor unavailable or malformed size.' }
    $anchorMetadata[$path] = @($item.Length, $item.LastWriteTimeUtc.Ticks)
}
# Nonsecret machine anchor binds explicit stopped-Core DataRoot to this install.
$machinePath = Join-Path $data 'config\zagent.machine.json'
$machineBytes = Read-BoundedBytes $machinePath
$machine = (Read-StrictJson $machineBytes).Object
if ($machine.install_root.TrimEnd('\') -ine $InstallRoot -or $machine.data_root.TrimEnd('\') -ine $data) { throw 'Enrolled installation/DataRoot anchor mismatch.' }
$paths = @{
    profiles = Join-Path $data 'files\config\profiles.json'
    commands = Join-Path $data 'files\config\remote_execution_policy.json'
    grant = Join-Path $data 'tunnel\config\tunnel.json'
}
$before = @{}
foreach ($name in @('profiles','commands','grant')) { $before[$name] = Read-BoundedBytes $paths[$name] }
$expectedRoot = 'D:\3-Ikbalzohr\Agent'
$legacyRoot = 'D:\3-Ikbalzohr\Agent\phyton_zagent_multiplatform\workspace'
$plan = New-OwnerProfileActivationPlan $before.profiles $before.commands $before.grant $expectedRoot $legacyRoot $AllowedProfileIds
if ([Convert]::ToBase64String($plan.Profiles) -ceq [Convert]::ToBase64String($before.profiles) -and
    [Convert]::ToBase64String($plan.Commands) -ceq [Convert]::ToBase64String($before.commands) -and
    [Convert]::ToBase64String($plan.Grant) -ceq [Convert]::ToBase64String($before.grant)) {
    Assert-CoreStopped
    foreach ($name in @('profiles','commands','grant')) { Assert-SnapshotUnchanged $paths[$name] $before[$name] }
    Write-Host 'OWNER_PROFILE_ALREADY_CURRENT; no files/backups written, no new approval, Core remains stopped.'
    return
}
Write-Host ('Default local/remote: agentRoot; root=' + $expectedRoot)
Write-Host ('Explicit allowed_profile_ids: ' + ($AllowedProfileIds -join ','))
Write-Host 'Remove ONLY appBridge configuration row, policy entry and allowlist membership. No folders, contents, sessions or databases are deleted.'
Write-Host 'Grant expires_at remains 1793539666; revocation/scopes/tools/issuer/workspace/device/installation and OAuth remain unchanged.'
Write-Host ('Exact reused executable allowlist (' + $plan.Executables.Count + '):')
$plan.Executables | ForEach-Object { Write-Host ('  ' + $_) }
Write-Host ('Exact reused limits: timeout=' + $plan.Timeout + '; output=' + $plan.Output + '; tools=' + ($plan.Tools -join ','))
Write-Host 'WARNING: commands at NEW root run with this Windows owner rights, not an OS sandbox. CWD/allowlists do not constrain all filesystem/network effects.'
if ((Read-Host 'Type ALLOW OWNER ACCOUNT EXECUTION AT agentRoot') -cne 'ALLOW OWNER ACCOUNT EXECUTION AT agentRoot') { throw 'Cancelled; no writes.' }
if ((Read-Host 'Type DEFAULT agentRoot REMOVE appBridge CONFIG ONLY') -cne 'DEFAULT agentRoot REMOVE appBridge CONFIG ONLY') { throw 'Cancelled; no writes.' }
Assert-CoreStopped
Assert-SnapshotUnchanged $machinePath $machineBytes
foreach ($path in $anchorMetadata.Keys) {
    Assert-MigrationPrivatePath $path
    $item = Get-Item -LiteralPath $path -Force
    if ($item.PSIsContainer -or $item.Length -ne $anchorMetadata[$path][0] -or $item.LastWriteTimeUtc.Ticks -ne $anchorMetadata[$path][1]) { throw 'Enrollment anchor changed during approval; no writes.' }
}
# Revalidate ALL candidates (including live paths/expiry) after the local pause.
$check = New-OwnerProfileActivationPlan $before.profiles $before.commands $before.grant $expectedRoot $legacyRoot $AllowedProfileIds
$entries = @{
    profiles = @{ Path = $paths.profiles; Before = $before.profiles; Next = $check.Profiles }
    commands = @{ Path = $paths.commands; Before = $before.commands; Next = $check.Commands }
    grant = @{ Path = $paths.grant; Before = $before.grant; Next = $check.Grant }
}
Invoke-OwnerProfileActivationCommit $entries
Write-Host 'ACTIVATION_APPLIED locally; Core NOT_STARTED. Preserve recovery receipts. No renewal, new certificate or new login was performed.'

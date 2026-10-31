# Internal guard invoked by owner_search_recovery.py; never an MCP handler.
[CmdletBinding()]
param(
 [Parameter(Mandatory=$true)][string]$InstallRoot,
 [Parameter(Mandatory=$true)][string]$DataRoot,
 [Parameter(Mandatory=$true)][string]$OwnerPrincipal,
 [Parameter(Mandatory=$true)][int]$RecoveryPid
)
$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
$stage='OWNER_CONSOLE'
try {
 . (Join-Path $PSScriptRoot 'WindowsDashboard-Provisioning.ps1')
 Assert-ZagentOwnerConsole
 $stage='SOURCE_PATH'
 foreach ($p in @($InstallRoot,$DataRoot)) {
  if ($p -cnotmatch '\A[A-Za-z]:\\' -or -not (Test-Path -LiteralPath $p -PathType Container)) { throw 'path' }
  Assert-ZagentPlainPath $p
 }
 $install=[IO.Path]::GetFullPath($InstallRoot).TrimEnd('\')
 $data=[IO.Path]::GetFullPath($DataRoot).TrimEnd('\')
 if ([IO.Path]::GetFullPath($PSScriptRoot).TrimEnd('\') -ine (Join-Path $install 'packaging\scripts')) { throw 'source' }
 . (Join-Path $PSScriptRoot 'Owner-PrivateConfig.ps1')
 . (Join-Path $PSScriptRoot 'ProfileAdministrationBootstrap.ps1')
 $stage='DATAROOT_ACL'
 Assert-ZagentOwnerAcl $data
 $stage='STOPPED_PRODUCERS'
 Assert-ProfileAdminCoreStopped
 # Actual Core factories supervise Python (Router/Files/ArcMap) and Node (Web).
 # Deny ambiguous hosts anywhere, not just ones whose path we can identify.
 $hosts=@(Get-CimInstance Win32_Process -Filter "Name='python.exe' OR Name='pythonw.exe' OR Name='python3.exe' OR Name='node.exe'" -ErrorAction Stop)
 if (@($hosts | Where-Object { $_.ProcessId -ne $RecoveryPid }).Count -ne 0) { throw 'host' }
 $self=@($hosts | Where-Object { $_.ProcessId -eq $RecoveryPid })
 if ($self.Count -ne 1 -or [int]$self[0].ProcessId -ne $RecoveryPid) { throw 'recovery process' }
 $guardProcess=Get-CimInstance Win32_Process -Filter ("ProcessId="+$PID) -ErrorAction Stop
 if ([int]$guardProcess.ParentProcessId -ne $RecoveryPid) { throw 'parent' }
 $stage='ENROLLMENT'
 $machinePath=Join-Path $data 'config\zagent.machine.json'
 $identityPath=Join-Path $data 'config\device_identity.json'
 $configPath=Join-Path $data 'tunnel\config\tunnel.json'
 $machineBytes=Read-BoundedBytes $machinePath
 $identityBytes=Read-BoundedBytes $identityPath
 $configBytes=Read-BoundedBytes $configPath
 $machine=(Read-StrictJson $machineBytes).Object
 $identity=(Read-StrictJson $identityBytes).Object
 $rs=(Read-StrictJson $configBytes).Object.resource_server
 if ($machine.install_root.TrimEnd('\') -ine $install -or $machine.data_root.TrimEnd('\') -ine $data -or
     $identity.schema_version -cne '2.0' -or $identity.protection -cne 'Windows DPAPI CurrentUser') { throw 'binding' }
 foreach ($id in @($identity.device_id,$identity.installation_id,$rs.workspace_id,$OwnerPrincipal)) {
  if ($id -isnot [string] -or [string]::IsNullOrWhiteSpace($id) -or $id.Length -gt 512 -or $id -match '[\x00-\x1f]') { throw 'identity' }
 }
 $entry=$rs.grants.PSObject.Properties[$OwnerPrincipal]
 if ($null -eq $entry) { throw 'owner' }
 $grant=$entry.Value; $resource=$grant.files_resource
 $grantRevoked=$grant.PSObject.Properties['revoked']
 $resourceRevoked=$resource.PSObject.Properties['revoked']
 # Match the existing optional-false revocation contract without accepting
 # malformed explicit values. StrictMode must not reject an absent member.
 if (($null -ne $grantRevoked -and ($grantRevoked.Value -isnot [bool] -or $grantRevoked.Value -ne $false)) -or
     ($null -ne $resourceRevoked -and ($resourceRevoked.Value -isnot [bool] -or $resourceRevoked.Value -ne $false)) -or $resource.kind -cne 'files' -or
     $resource.device_id -cne $identity.device_id -or $resource.installation_id -cne $identity.installation_id -or
     $resource.resource_id -isnot [string] -or [string]::IsNullOrWhiteSpace($resource.resource_id)) { throw 'owner resource' }
 $stage='JOURNAL_ACL'
 $journal=Join-Path $data 'tunnel\runtime\tasks.db'
 if (-not (Test-Path -LiteralPath $journal -PathType Leaf)) { throw 'journal' }
 Assert-MigrationPrivatePath $journal
 foreach ($suffix in @('-wal','-shm','-journal')) {
  $side=$journal+$suffix
  if (Test-Path -LiteralPath $side) { Assert-MigrationPrivatePath $side }
 }
 $hash=[Security.Cryptography.SHA256]::Create()
 try {
  $snapshots=@($machineBytes,$identityBytes,$configBytes) | ForEach-Object { [Convert]::ToBase64String($hash.ComputeHash([byte[]]$_)) }
 } finally { $hash.Dispose() }
 [ordered]@{principal_id=$OwnerPrincipal;workspace_id=$rs.workspace_id;device_id=$identity.device_id;installation_id=$identity.installation_id;resource_id=$resource.resource_id;owner_sid=[Security.Principal.WindowsIdentity]::GetCurrent().User.Value;config_snapshots=$snapshots} | ConvertTo-Json -Compress
} catch {
 # No paths, config contents, command lines or exception messages leave this guard.
 Write-Output ('{"denied":"'+$stage+'"}')
 exit 1
}

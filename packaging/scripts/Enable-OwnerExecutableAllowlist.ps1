<#
Owner-local public allowlist bootstrap prerequisite/plan package (NOT an activator).
PlanOnly reads enrolled inputs locally, executes the pure public planner, and writes NOTHING.
Never run against installed private state via MCP. Agent tests must use disposable fixtures.
Publication is deliberately disabled until the coordinator runtime/source contract is reviewed.
No key generation, private-key import, laptop backup, grant/policy patch, or Core lifecycle action.
#>
[CmdletBinding()]
param(
 [Parameter(Mandatory)][string]$InstallRoot,
 [Parameter(Mandatory)][string]$DataRoot,
 [Parameter(Mandatory)][string]$PublicBundle,
 [Parameter(Mandatory)][ValidatePattern('^[0-9a-f]{64}$')][string]$BundleSha256,
 [Parameter(Mandatory)][string]$OwnerPrincipal,
 [Parameter(Mandatory)][string]$WorkspaceId,
 [Parameter(Mandatory)][string]$DeviceId,
 [Parameter(Mandatory)][string]$InstallationId,
 [Parameter(Mandatory)][string]$PythonExecutable,
 [switch]$PlanOnly
)
$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
# Storage primitive only. The entrypoint below does not call it until runtime hosting
# has a reviewed contract. No caller-supplied gate/console bypass is exposed.
function Publish-ZagentBootstrapCandidate {
 [CmdletBinding()]
 param([Parameter(Mandatory)][string]$DataRoot,
       [Parameter(Mandatory)][Collections.IDictionary]$Files,
       [Parameter(Mandatory)][array]$Snapshots)
 $names=@('approval.pub','capability.json','owner.json','request.pub','transport.pub')
 if ((@($Files.Keys|Sort-Object) -join ',') -cne ($names -join ',') -or $Snapshots.Count -lt 1 -or $Snapshots.Count -gt 8) {throw 'Invalid publication shape'}
 foreach ($name in $names) {if ($Files[$name] -isnot [byte[]] -or $Files[$name].Length -lt 1 -or $Files[$name].Length -gt 65536) {throw 'Invalid bounded artifact'}}
 Assert-ZagentOwnerAcl $DataRoot
 $root=[IO.Path]::GetFullPath($DataRoot).TrimEnd('\')
 # A protected child cannot defend against delete-child/rename rights above it.
 # Match the native loader's conservative ancestor owner/write restrictions.
 $ownerSid=[Security.Principal.WindowsIdentity]::GetCurrent().User.Value
 $trusted=@($ownerSid,'S-1-5-18','S-1-5-32-544')
 $standard=@($trusted)+@('S-1-5-80-956008885-3418522649-1831038044-1853292631-2271478464')
 $ancestor=[IO.DirectoryInfo]::new($root).Parent
 while ($null -ne $ancestor) {
  $acl=Get-Acl -LiteralPath $ancestor.FullName
  if ($acl.GetOwner([Security.Principal.SecurityIdentifier]).Value -cnotin $standard) {throw 'Unsafe publication ancestor'}
  $writeMask=[long]0x500D0156
  if ($null -eq $ancestor.Parent) {$writeMask=$writeMask -band (-bnot [long]4)}
  $rawAcl=[Security.AccessControl.RawSecurityDescriptor]::new($acl.GetSecurityDescriptorBinaryForm(),0).DiscretionaryAcl
  if ($null -eq $rawAcl) {throw 'Unsafe publication ancestor'}
  foreach ($ace in $rawAcl) {if ($ace.AceType -notin @([Security.AccessControl.AceType]::AccessAllowed,[Security.AccessControl.AceType]::AccessDenied)) {throw 'Unsafe publication ancestor'}}
  foreach ($rule in $acl.GetAccessRules($true,$true,[Security.Principal.SecurityIdentifier])) {
   if (($rule.PropagationFlags -band [Security.AccessControl.PropagationFlags]::InheritOnly) -ne 0) {continue}
   if ($rule.AccessControlType -eq [Security.AccessControl.AccessControlType]::Allow -and $rule.IdentityReference.Value -cnotin $trusted -and (([long]$rule.FileSystemRights -band $writeMask) -ne 0)) {throw 'Unsafe publication ancestor'}
  }
  $ancestor=$ancestor.Parent
 }
 $destination=Join-Path $root 'allowlist'
 Assert-ZagentPlainPath $destination
 if (Test-Path -LiteralPath $destination) {throw 'Enrollment exists; never overwrite'}
 $sid=[Security.Principal.WindowsIdentity]::GetCurrent().User
 # Persist owner/DACL sections only; never request SACL privileges or adopt objects.
 $fileAcl=[Security.AccessControl.FileSecurity]::new();$fileAcl.SetOwner($sid);$fileAcl.SetAccessRuleProtection($true,$false)
 $fileAcl.AddAccessRule([Security.AccessControl.FileSystemAccessRule]::new($sid,'FullControl','Allow'))
 $directoryAcl=[Security.AccessControl.DirectorySecurity]::new();$directoryAcl.SetOwner($sid);$directoryAcl.SetAccessRuleProtection($true,$false)
 $directoryAcl.AddAccessRule([Security.AccessControl.FileSystemAccessRule]::new($sid,'FullControl','ContainerInherit,ObjectInherit','None','Allow'))
 $lock=$null;$stagePath=$null;$readers=[Collections.Generic.List[IO.FileStream]]::new()
 try {
  $lockPath=Join-Path $root '.allowlist-bootstrap.lock';Assert-ZagentPlainPath $lockPath
  if (Test-Path -LiteralPath $lockPath) {
   Assert-ZagentOwnerAcl $lockPath
   $lock=[IO.File]::Open($lockPath,[IO.FileMode]::Open,[IO.FileAccess]::ReadWrite,[IO.FileShare]::None)
  } else {
   $lock=[IO.File]::Open($lockPath,[IO.FileMode]::CreateNew,[IO.FileAccess]::ReadWrite,[IO.FileShare]::None)
   [IO.FileSystemAclExtensions]::SetAccessControl([IO.FileInfo]::new($lockPath),$fileAcl)
  }
  # Read-only sharing denies writers and deletion until publication finishes.
  foreach ($snapshot in $Snapshots) {
   $path=[IO.Path]::GetFullPath($snapshot.Path)
   if (-not $path.StartsWith(($root+'\'),[StringComparison]::OrdinalIgnoreCase) -or $snapshot.Bytes -isnot [byte[]] -or $snapshot.Bytes.Length -gt 1048576) {throw 'Invalid source snapshot'}
   Assert-ZagentPlainPath $path
   $reader=[IO.File]::Open($path,[IO.FileMode]::Open,[IO.FileAccess]::Read,[IO.FileShare]::Read);$readers.Add($reader)
   if ($reader.Length -ne $snapshot.Bytes.Length) {throw 'Source CAS conflict'}
   $digest=[Security.Cryptography.SHA256]::HashData($reader)
   if ([Convert]::ToHexString($digest) -cne [Convert]::ToHexString([Security.Cryptography.SHA256]::HashData($snapshot.Bytes))) {throw 'Source CAS conflict'}
  }
  Assert-ZagentOwnerAcl $root;Assert-ZagentPlainPath $destination
  if (Test-Path -LiteralPath $destination) {throw 'Enrollment appeared; never overwrite'}
  $stagePath=Join-Path $root ('.allowlist-stage-'+[guid]::NewGuid().ToString('N'))
  if (Test-Path -LiteralPath $stagePath) {throw 'Fresh staging required'}
  [IO.Directory]::CreateDirectory($stagePath)|Out-Null
  [IO.FileSystemAclExtensions]::SetAccessControl([IO.DirectoryInfo]::new($stagePath),$directoryAcl)
  Assert-ZagentOwnerAcl $stagePath
  foreach ($name in @('journal','replay')) {
   $child=Join-Path $stagePath $name;[IO.Directory]::CreateDirectory($child)|Out-Null
   # Security descriptors track dirty sections and SetAccessControl clears them.
   $childAcl=[Security.AccessControl.DirectorySecurity]::new()
   $childAcl.SetSecurityDescriptorBinaryForm($directoryAcl.GetSecurityDescriptorBinaryForm(),([Security.AccessControl.AccessControlSections]::Owner -bor [Security.AccessControl.AccessControlSections]::Access))
   [IO.FileSystemAclExtensions]::SetAccessControl([IO.DirectoryInfo]::new($child),$childAcl);Assert-ZagentOwnerAcl $child
  }
  foreach ($name in $names) {
   $path=Join-Path $stagePath $name
   $stream=[IO.File]::Open($path,[IO.FileMode]::CreateNew,[IO.FileAccess]::Write,[IO.FileShare]::None)
   try {$stream.Write($Files[$name],0,$Files[$name].Length);$stream.Flush($true)} finally {$stream.Dispose()}
   $artifactAcl=[Security.AccessControl.FileSecurity]::new()
   $artifactAcl.SetSecurityDescriptorBinaryForm($fileAcl.GetSecurityDescriptorBinaryForm(),([Security.AccessControl.AccessControlSections]::Owner -bor [Security.AccessControl.AccessControlSections]::Access))
   [IO.FileSystemAclExtensions]::SetAccessControl([IO.FileInfo]::new($path),$artifactAcl);Assert-ZagentOwnerAcl $path
   if ([Convert]::ToBase64String([IO.File]::ReadAllBytes($path)) -cne [Convert]::ToBase64String($Files[$name])) {throw 'Candidate readback mismatch'}
  }
  Assert-ZagentOwnerAcl $root;Assert-ZagentPlainPath $destination
  # Same-volume rename is the sole commit point and never replaces an existing target.
  [IO.Directory]::Move($stagePath,$destination);$stagePath=$null
  Assert-ZagentOwnerAcl $destination
  foreach ($name in $names) {
   $path=Join-Path $destination $name;Assert-ZagentOwnerAcl $path
   if ([Convert]::ToBase64String([IO.File]::ReadAllBytes($path)) -cne [Convert]::ToBase64String($Files[$name])) {throw 'Published readback mismatch; outcome requires inspection'}
  }
 } finally {
  foreach ($reader in $readers) {$reader.Dispose()}
  if ($null -ne $lock) {$lock.Dispose()}
  # Never remove a published destination or a retained prior-run candidate.
  if ($null -ne $stagePath -and (Test-Path -LiteralPath $stagePath)) {Assert-ZagentPlainPath $stagePath;Remove-Item -LiteralPath $stagePath -Recurse -Force}
 }
}
$stage='dependencies'
try {
 foreach ($dependency in @('WindowsDashboard-Provisioning.ps1','Owner-PrivateConfig.ps1','ProfileAdministrationBootstrap.ps1')) {
  $dependencyPath=Join-Path $PSScriptRoot $dependency
  if (-not (Test-Path -LiteralPath $dependencyPath -PathType Leaf)) {throw 'Missing packaged dependency'}
  . $dependencyPath
 }
 foreach ($function in @('Assert-ZagentOwnerConsole','Assert-ZagentPlainPath','Assert-ZagentOwnerAcl','Assert-MigrationPrivatePath','Read-BoundedBytes','Read-StrictJson','Assert-SnapshotUnchanged','Assert-ProfileAdminCoreStopped')) {
  if (-not (Get-Command -Name $function -CommandType Function -ErrorAction SilentlyContinue)) {throw 'Missing reviewed function'}
 }
 $stage='owner-console'
 if (-not [Runtime.InteropServices.RuntimeInformation]::IsOSPlatform([Runtime.InteropServices.OSPlatform]::Windows)) {throw 'Windows required'}
 if (-not $PlanOnly) {Assert-ZagentOwnerConsole}
 $identity=[Security.Principal.WindowsIdentity]::GetCurrent()
 if ($identity.IsSystem -or $identity.IsAnonymous -or $null -eq $identity.User) {throw 'Owner SID required'}
 $stage='paths'
 foreach ($path in @($InstallRoot,$DataRoot,$PublicBundle,$PythonExecutable)) {
  if ($path -cnotmatch '\A[A-Za-z]:\\' -or $path -match '[\x00-\x1f]') {throw 'Absolute local path required'}
  Assert-ZagentPlainPath $path
  if (-not (Test-Path -LiteralPath $path)) {throw 'Existing path required'}
 }
 $InstallRoot=(Resolve-Path -LiteralPath $InstallRoot).Path.TrimEnd('\')
 $data=(Resolve-Path -LiteralPath $DataRoot).Path.TrimEnd('\')
 $stage='private-acl'
 Assert-ZagentOwnerAcl $data
 foreach ($value in @($OwnerPrincipal,$WorkspaceId,$DeviceId,$InstallationId)) {
  if ([string]::IsNullOrWhiteSpace($value) -or $value -cne $value.Trim() -or $value.Length -gt 256 -or $value -match '[\x00-\x1f]') {throw 'Explicit bounded placement required'}
 }
 $stage='machine-placement'
 $machinePath=Join-Path $data 'config\zagent.machine.json'
 $machineBytes=Read-BoundedBytes $machinePath
 $machine=(Read-StrictJson $machineBytes).Object
 if ($machine.install_root -isnot [string] -or $machine.data_root -isnot [string] -or
     $machine.install_root.TrimEnd('\') -ine $InstallRoot -or $machine.data_root.TrimEnd('\') -ine $data) {throw 'Enrolled placement mismatch'}
 $stage='owner-grant'
 $grantPath=Join-Path $data 'tunnel\config\tunnel.json'
 $grantBytes=Read-BoundedBytes $grantPath
 $tunnel=(Read-StrictJson $grantBytes).Object
 $rs=$tunnel.resource_server
 if ($rs.workspace_id -isnot [string] -or $rs.workspace_id -cne $WorkspaceId -or $rs.grants -isnot [pscustomobject]) {throw 'Workspace mismatch'}
 $property=@($rs.grants.PSObject.Properties | Where-Object Name -CEQ $OwnerPrincipal)
 if ($property.Count -ne 1) {throw 'Exact existing principal required'}
 $grant=$property[0].Value
 if ($grant.revoked -isnot [bool] -or $grant.revoked -ne $false -or
     ($grant.expires_at -isnot [long] -and $grant.expires_at -isnot [int]) -or
     $grant.expires_at -le [DateTimeOffset]::UtcNow.ToUnixTimeSeconds()) {throw 'Finite current nonrevoked grant required'}
 foreach ($list in @('scopes','tools')) {
  if ($grant.$list -isnot [array] -or $grant.$list.Count -lt 1 -or $grant.$list.Count -gt 512) {throw 'Bounded string list required'}
  $seen=[Collections.Generic.HashSet[string]]::new([StringComparer]::Ordinal)
  foreach ($value in $grant.$list) {if ($value -isnot [string] -or [string]::IsNullOrWhiteSpace($value) -or $value.Length -gt 256 -or -not $seen.Add($value)) {throw 'Invalid grant list'}}
 }
 $stage='dedicated-admin-authority'
 # This static check is NOT proof an OAuth token has the dedicated scope. Never add it here.
 foreach ($scope in @('files:read','files:write','allowlist-admin')) {if ($scope -cnotin $grant.scopes) {throw 'Preprovisioned dedicated scope required'}}
 foreach ($tool in @('allowlist_admin_list','files_profile_admin_list')) {
  if ($tool -cnotin $grant.tools) {throw 'Preprovisioned exact tool required'}
  $scope='allowlist-admin';if ($tool -ceq 'files_profile_admin_list') {$scope='files:read'}
  $rule=$tunnel.tool_policy.PSObject.Properties[$tool].Value
  if ($rule.scope -isnot [string] -or $rule.scope -cne $scope -or
      ($null -ne $rule.PSObject.Properties['enabled'] -and ($rule.enabled -isnot [bool] -or $rule.enabled -ne $true))) {throw 'Exact enabled tool scope policy required'}
 }
 $stage='profile-management'
 $cap=$grant.profile_management
 if ($cap -isnot [pscustomobject] -or @($cap.PSObject.Properties).Count -ne 6 -or
     ($cap.version -isnot [int] -and $cap.version -isnot [long]) -or $cap.version -ne 1 -or
     $cap.enabled -isnot [bool] -or $cap.enabled -ne $true -or
     $cap.workspace_id -isnot [string] -or $cap.workspace_id -cne $WorkspaceId -or
     $cap.device_id -isnot [string] -or $cap.device_id -cne $DeviceId -or
     $cap.installation_id -isnot [string] -or $cap.installation_id -cne $InstallationId -or
     $cap.actions -isnot [array] -or $cap.actions.Count -lt 1 -or $cap.actions.Count -gt 6 -or 'list' -cnotin $cap.actions) {throw 'Existing profile capability required'}
 $seen=[Collections.Generic.HashSet[string]]::new([StringComparer]::Ordinal)
 foreach ($action in $cap.actions) {if ($action -isnot [string] -or $action -cnotin @('list','get','create','update','delete','set_default') -or -not $seen.Add($action)) {throw 'Invalid existing actions'}}
 $stage='files-placement'
 $r=$grant.files_resource
 if ($r.kind -isnot [string] -or $r.kind -cne 'files' -or $r.revoked -isnot [bool] -or $r.revoked -ne $false -or
     $r.device_id -isnot [string] -or $r.device_id -cne $DeviceId -or
     $r.installation_id -isnot [string] -or $r.installation_id -cne $InstallationId -or
     $r.resource_id -isnot [string] -or [string]::IsNullOrWhiteSpace($r.resource_id) -or
     $r.profile_id -isnot [string]) {throw 'Existing Files placement required'}
 $ids=@($r.profile_id)
 if ($null -ne $r.PSObject.Properties['allowed_profile_ids']) {$ids=$r.allowed_profile_ids}
 if ($ids -isnot [array] -or $ids.Count -lt 1 -or $ids.Count -gt 128 -or $r.profile_id -cnotin $ids -or 'agentRoot' -cnotin $ids) {throw 'Existing delegation required'}
 $seen=[Collections.Generic.HashSet[string]]::new([StringComparer]::Ordinal)
 foreach ($id in $ids) {if ($id -isnot [string] -or $id -cnotmatch '\A[A-Za-z0-9_-]{1,256}\z' -or -not $seen.Add($id)) {throw 'Invalid membership'}}
 $stage='profile-root-exclusion'
 $profilesPath=Join-Path $data 'files\config\profiles.json'
 $profilesBytes=Read-BoundedBytes $profilesPath
 $profiles=(Read-StrictJson $profilesBytes).Object
 if ($profiles.profiles -isnot [array]) {throw 'Profile array required'}
 foreach ($profile in $profiles.profiles) {
  if ($profile.root -isnot [string] -or $profile.root -cnotmatch '\A[A-Za-z]:\\') {throw 'Absolute profile root required'}
  Assert-ZagentPlainPath $profile.root
  $root=[IO.Path]::GetFullPath($profile.root).TrimEnd('\')
  if ($data -ieq $root -or $data.StartsWith(($root+'\'),[StringComparison]::OrdinalIgnoreCase) -or
      $root.StartsWith(($data+'\'),[StringComparison]::OrdinalIgnoreCase)) {throw 'Private DataRoot overlaps a Files root'}
 }
 $rows=@($profiles.profiles | Where-Object {$_.name -is [string] -and $_.name -ceq 'agentRoot'})
 if ($rows.Count -ne 1) {throw 'Exactly one agentRoot required'}
 $row=$rows[0]
 if ($row.enabled -isnot [bool] -or $row.enabled -ne $true -or $row.authorized_by_user -isnot [bool] -or $row.authorized_by_user -ne $true -or
     $row.mode -isnot [string] -or $row.mode -cne 'read-write' -or $row.root -cne 'D:\3-Ikbalzohr\Agent') {throw 'Exact approved agentRoot required'}
 $stage='command-policy'
 $policyPath=Join-Path $data 'files\config\remote_execution_policy.json'
 $policyBytes=Read-BoundedBytes $policyPath
 $policy=(Read-StrictJson $policyBytes).Object
 $cp=$policy
 if (($policy.version -is [int] -or $policy.version -is [long]) -and $policy.version -eq 2) {$cp=$policy.profiles.agentRoot}
 if ($cp.profile_id -isnot [string] -or $cp.profile_id -cne 'agentRoot' -or $cp.enabled -isnot [bool] -or $cp.enabled -ne $true -or
     $cp.acknowledge_host_access -isnot [bool] -or $cp.acknowledge_host_access -ne $true -or
     $cp.execution_mode -isnot [string] -or $cp.execution_mode -cne 'owner-account' -or $cp.root -isnot [string] -or $cp.root -cne $row.root) {throw 'Existing exact owner-account policy required'}
 $stage='no-overwrite'
 Assert-ZagentPlainPath (Join-Path $data 'allowlist')
 if (Test-Path -LiteralPath (Join-Path $data 'allowlist')) {throw 'Enrollment exists; offline recovery only'}
 $stage='public-bundle'
 $stream=[IO.File]::Open($PublicBundle,[IO.FileMode]::Open,[IO.FileAccess]::Read,[IO.FileShare]::Read)
 try {
  if ($stream.Length -lt 2 -or $stream.Length -gt 16384) {throw 'Public bundle bound'}
  $bundle=New-Object byte[] ([int]$stream.Length);$offset=0
  while ($offset -lt $bundle.Length) {$n=$stream.Read($bundle,$offset,$bundle.Length-$offset);if ($n -eq 0) {throw 'Bundle changed'};$offset+=$n}
  if ($stream.ReadByte() -ne -1) {throw 'Bundle grew'}
 } finally {$stream.Dispose()}
 $hash=[Convert]::ToHexString([Security.Cryptography.SHA256]::HashData($bundle)).ToLowerInvariant()
 if ($hash -cne $BundleSha256) {throw 'Raw public bundle acknowledgement mismatch'}
 $stage='pure-planner'
 $expiry=[long][Math]::Min($grant.expires_at,([DateTimeOffset]::UtcNow.ToUnixTimeSeconds()+365*86400))
 $inputs=@{bundle=[Convert]::ToBase64String($bundle);acknowledged_sha256=$hash;placement=@{principal_id=$OwnerPrincipal;workspace_id=$WorkspaceId;device_id=$DeviceId;installation_id=$InstallationId;target_profile_id='agentRoot'};data_root=$data;policy_path=$policyPath;profiles_path=$profilesPath;owner_sid=$identity.User.Value;expires_at=$expiry}
 $oldPython=$env:PYTHONPATH;$oldBytecode=$env:PYTHONDONTWRITEBYTECODE
 try {
  $env:PYTHONPATH=Join-Path $InstallRoot 'agents\files\engine';$env:PYTHONDONTWRITEBYTECODE='1'
  $json=$inputs|ConvertTo-Json -Depth 12 -Compress
  # Use the explicitly selected Python executable, never a PATH-resolved fallback.
  # ProcessStartInfo also avoids native pipeline launch ambiguity in clean MCP environments.
  $start=[Diagnostics.ProcessStartInfo]::new()
  $start.FileName=$PythonExecutable;$start.UseShellExecute=$false;$start.CreateNoWindow=$true
  $start.WorkingDirectory=$InstallRoot
  foreach ($argument in @('-B','-m','app.allowlist.bootstrap')) {$start.ArgumentList.Add($argument)}
  $start.RedirectStandardInput=$true;$start.RedirectStandardOutput=$true;$start.RedirectStandardError=$true
  $process=[Diagnostics.Process]::new();$process.StartInfo=$start
  try {
   if (-not $process.Start()) {throw 'Pure planner did not start'}
   $stdout=$process.StandardOutput.ReadToEndAsync();$stderr=$process.StandardError.ReadToEndAsync()
   $process.StandardInput.Write($json);$process.StandardInput.Close()
   if (-not $process.WaitForExit(30000)) {$process.Kill($true);throw 'Pure planner timeout'}
   $result=$stdout.GetAwaiter().GetResult();$null=$stderr.GetAwaiter().GetResult()
   if ($process.ExitCode -ne 0 -or $result.Length -gt 65536) {throw 'Pure planner rejected bundle'}
   $plan=(Read-StrictJson ([Text.Encoding]::UTF8.GetBytes($result))).Object
  } finally {$process.Dispose()}
 } finally {$env:PYTHONPATH=$oldPython;$env:PYTHONDONTWRITEBYTECODE=$oldBytecode}
 $names=@('approval.pub','capability.json','owner.json','request.pub','transport.pub')
 if (($plan.files.PSObject.Properties.Name|Sort-Object) -join ',' -cne ($names -join ',') -or $plan.bundle_sha256 -cne $hash) {throw 'Unexpected planner artifacts'}
 # Existing pure planner manifest pins an unverified runtime URL. No bypass switch is exposed.
 # It also predates the Router capability-source mutations_ready field. Do NOT publish it.
 $stage='snapshot-invariance'
 Assert-SnapshotUnchanged $machinePath $machineBytes
 Assert-SnapshotUnchanged $grantPath $grantBytes
 Assert-SnapshotUnchanged $profilesPath $profilesBytes
 Assert-SnapshotUnchanged $policyPath $policyBytes
 if (-not $PlanOnly) {
  $stage='core-maintenance';Assert-ProfileAdminCoreStopped
  $stage='runtime-contract';throw 'Publication unavailable pending reviewed runtime contract'
 }
 [ordered]@{status='PLAN_VERIFIED_BLOCKED';bundle_sha256=$hash;file_count=5;public_roles=@('approval:Ed25519','request:Ed25519','transport:X25519');expires_at=$expiry;mutations_ready=$false;enrollment_ready=$false;no_writes=$true;blockers=@('RUNTIME_CONTRACT_UNVERIFIED','ROUTER_SOURCE_CONTRACT_UNVERIFIED','OAUTH_DEDICATED_SCOPE_NOT_VERIFIED');core_action='NOT_RUN';publication='NOT_IMPLEMENTED_PENDING_CONTRACT'}|ConvertTo-Json -Depth 6 -Compress
} catch {
 # Stage vocabulary only: never expose private JSON, paths, credentials or nested exceptions.
 throw ('ALLOWLIST_BOOTSTRAP_BLOCKED stage='+$stage+'; NO_WRITES; mutations_ready=false')
}

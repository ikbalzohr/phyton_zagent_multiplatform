[CmdletBinding()]
param([Parameter(Mandatory)][string]$PythonExecutable)
$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
$repo=Split-Path $PSScriptRoot -Parent
$helper=Join-Path $repo 'packaging\scripts\Enable-OwnerExecutableAllowlist.ps1'
if (-not (Test-Path -LiteralPath $helper)) { throw 'ASSERT: packaged owner helper is missing' }
. (Join-Path $repo 'packaging\scripts\WindowsDashboard-Provisioning.ps1')
# Temp can grant write/delete-child to another SID; the real loader must reject it.
# A fresh owner-ACL fixture under LocalApplicationData avoids that unsafe ancestor.
$base=Join-Path ([Environment]::GetFolderPath([Environment+SpecialFolder]::LocalApplicationData)) ('zagent-allowlist-owner-fixture-'+[guid]::NewGuid().ToString('N'))
New-ZagentPrivateDirectory $base
$data=Join-Path $base 'private';New-ZagentPrivateDirectory $data
$install=$repo
$placement=[ordered]@{device_id='fixture-device';installation_id='fixture-installation';principal_id='fixture-owner';target_profile_id='agentRoot';workspace_id='fixture-workspace'}
function Write-FixtureJson($relative,$value) {
 $path=Join-Path $data $relative
 $parent=Split-Path $path -Parent
 [IO.Directory]::CreateDirectory($parent)|Out-Null
 [IO.File]::WriteAllText($path,($value|ConvertTo-Json -Depth 20 -Compress),[Text.UTF8Encoding]::new($false))
}
$grant=[ordered]@{revoked=$false;expires_at=([DateTimeOffset]::UtcNow.ToUnixTimeSeconds()+86400);scopes=@('files:read','files:write','allowlist-admin');tools=@('allowlist_admin_list','files_profile_admin_list');files_resource=@{kind='files';revoked=$false;device_id=$placement.device_id;installation_id=$placement.installation_id;resource_id='fixture-resource';profile_id='agentRoot';allowed_profile_ids=@('agentRoot')};profile_management=@{version=1;enabled=$true;workspace_id=$placement.workspace_id;device_id=$placement.device_id;installation_id=$placement.installation_id;actions=@('list')}}
$tunnel=@{resource_server=@{workspace_id=$placement.workspace_id;grants=@{'fixture-owner'=$grant}};tool_policy=@{allowlist_admin_list=@{scope='allowlist-admin';enabled=$true};files_profile_admin_list=@{scope='files:read';enabled=$true}}}
Write-FixtureJson 'config\zagent.machine.json' @{install_root=$install;data_root=$data}
Write-FixtureJson 'tunnel\config\tunnel.json' $tunnel
Write-FixtureJson 'files\config\profiles.json' @{profiles=@(@{name='agentRoot';enabled=$true;authorized_by_user=$true;mode='read-write';root='D:\3-Ikbalzohr\Agent'})}
Write-FixtureJson 'files\config\remote_execution_policy.json' @{version=2;profiles=@{agentRoot=@{profile_id='agentRoot';enabled=$true;acknowledge_host_access=$true;execution_mode='owner-account';root='D:\3-Ikbalzohr\Agent'}}}
$keys=[ordered]@{}
$i=0
foreach ($role in @('approval','request','transport')) {
 $i++;$bytes=[byte[]](@($i)*32);$hash=[Convert]::ToHexString([Security.Cryptography.SHA256]::HashData($bytes)).ToLowerInvariant()
 $algorithm='Ed25519';if ($role -ceq 'transport') {$algorithm='X25519'}
 $keys[$role]=[ordered]@{algorithm=$algorithm;key_id=($role+'-'+$hash);public_key=([Convert]::ToBase64String($bytes).TrimEnd('=').Replace('+','-').Replace('/','_'));sha256=$hash}
}
$bundle=Join-Path $base 'public.json'
[IO.File]::WriteAllText($bundle,([ordered]@{keys=$keys;kind='zagent.allowlist.public-bootstrap.v1';placement=$placement;version=1}|ConvertTo-Json -Depth 12 -Compress),[Text.UTF8Encoding]::new($false))
$ack=(Get-FileHash -LiteralPath $bundle -Algorithm SHA256).Hash.ToLowerInvariant()
$params=@{InstallRoot=$install;DataRoot=$data;PublicBundle=$bundle;BundleSha256=$ack;OwnerPrincipal=$placement.principal_id;WorkspaceId=$placement.workspace_id;DeviceId=$placement.device_id;InstallationId=$placement.installation_id;PythonExecutable=$PythonExecutable}
function Get-FixtureSnapshot {
 @((Get-ChildItem -LiteralPath $base -Recurse -Force | Sort-Object FullName | ForEach-Object {if ($_.PSIsContainer) {'D '+$_.FullName} else {'F '+$_.FullName+' '+(Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash}})) -join "`n"
}
$script:passed=0
function Assert-Rejected([string]$name,[string]$expectedStage,[hashtable]$arguments=$params,[switch]$Apply) {
 $before=Get-FixtureSnapshot;$caught=$false
 try {if ($Apply) {& $helper @arguments|Out-Null} else {& $helper @arguments -PlanOnly|Out-Null}}
 catch {if ($_.Exception.Message -cne ('ALLOWLIST_BOOTSTRAP_BLOCKED stage='+$expectedStage+'; NO_WRITES; mutations_ready=false')) {throw ('ASSERT: unexpected stage for '+$name+': '+$_.Exception.Message)};$caught=$true}
 if (-not $caught) {throw ('ASSERT: accepted '+$name)}
 if ((Get-FixtureSnapshot) -cne $before) {throw ('ASSERT: helper wrote during '+$name)}
 $script:passed++;Write-Output ('PASS reject '+$name+'; NO_WRITES')
}
try {
 $before=Get-FixtureSnapshot
 $oldPython=$env:PYTHONPATH;$oldBytecode=$env:PYTHONDONTWRITEBYTECODE
 $result=(& $helper @params -PlanOnly) | ConvertFrom-Json
 if ($env:PYTHONPATH -cne $oldPython -or $env:PYTHONDONTWRITEBYTECODE -cne $oldBytecode) {throw 'ASSERT: process environment not restored'}
 if ($result.status -cne 'PLAN_VERIFIED_BLOCKED' -or $result.mutations_ready -cne $false -or $result.no_writes -cne $true -or $result.enrollment_ready -cne $false) {throw 'ASSERT: truthful blocked PlanOnly report required'}
 if ($result.bundle_sha256 -cne $ack -or $result.file_count -ne 5 -or 'RUNTIME_CONTRACT_UNVERIFIED' -cnotin $result.blockers) {throw 'ASSERT: plan artifact/hash/runtime blocker required'}
 if ($result.expires_at -gt $grant.expires_at -or $result.expires_at -le [DateTimeOffset]::UtcNow.ToUnixTimeSeconds() -or $result.public_roles.Count -ne 3) {throw 'ASSERT: finite expiry/public roles'}
 if ((Get-FixtureSnapshot) -cne $before) {throw 'ASSERT: PlanOnly wrote fixture bytes or directories'}
 $script:passed++;Write-Output 'PASS actual helper PlanOnly; five public/identity artifacts; NO_WRITES; runtime blocked'
 if (-not [Console]::IsInputRedirected) {throw 'ASSERT: noninteractive fixture must actually be redirected; no native guard simulation'}
 Assert-Rejected 'native redirected owner-console' 'owner-console' -Apply
 foreach ($field in @('OwnerPrincipal','WorkspaceId','DeviceId','InstallationId')) {
  $changed=$params.Clone();$changed[$field]='wrong-fixture-id'
  $expected='owner-grant';if ($field -ceq 'DeviceId' -or $field -ceq 'InstallationId') {$expected='profile-management'}
  Assert-Rejected ('placement-'+$field) $expected $changed
 }
 $changed=$params.Clone();$changed.BundleSha256='0'*64;Assert-Rejected 'raw-byte acknowledgement' 'public-bundle' $changed
 $oldScopes=$grant.scopes;$grant.scopes=@('files:read','files:write');Write-FixtureJson 'tunnel\config\tunnel.json' $tunnel
 Assert-Rejected 'no dedicated scope (ordinary Files insufficient)' 'dedicated-admin-authority'
 $grant.scopes=$oldScopes;$oldTools=$grant.tools;$grant.tools=@('files_profile_admin_list');Write-FixtureJson 'tunnel\config\tunnel.json' $tunnel
 Assert-Rejected 'no exact admin tool' 'dedicated-admin-authority'
 $grant.tools=$oldTools;$tunnel.tool_policy.allowlist_admin_list.scope='files:write';Write-FixtureJson 'tunnel\config\tunnel.json' $tunnel
 Assert-Rejected 'wrong exact tool scope policy' 'dedicated-admin-authority'
 $tunnel.tool_policy.allowlist_admin_list.scope='allowlist-admin';$grant.profile_management.enabled=$false;Write-FixtureJson 'tunnel\config\tunnel.json' $tunnel
 Assert-Rejected 'disabled profile management' 'profile-management'
 $grant.profile_management.enabled=$true
 foreach ($bad in @(@(),@('fixture-device'),$null,$true,@{value='fixture-device'})) {
  $grant.files_resource.device_id=$bad;Write-FixtureJson 'tunnel\config\tunnel.json' $tunnel
  Assert-Rejected 'nonscalar Files device identity' 'files-placement'
 }
 $grant.files_resource.device_id=$placement.device_id
 $oldExpiry=$grant.expires_at
 foreach ($bad in @($null,$false,0,'99999999999',@(),@($oldExpiry),@{value=$oldExpiry})) {
  $grant.expires_at=$bad;Write-FixtureJson 'tunnel\config\tunnel.json' $tunnel
  Assert-Rejected 'invalid/expired grant expiry' 'owner-grant'
 }
 $grant.expires_at=$oldExpiry;$grant.revoked=$true;Write-FixtureJson 'tunnel\config\tunnel.json' $tunnel
 Assert-Rejected 'revoked grant' 'owner-grant'
 $grant.revoked=$false;Write-FixtureJson 'tunnel\config\tunnel.json' $tunnel
 $profilesFile=Join-Path $data 'files\config\profiles.json';$oldProfiles=[IO.File]::ReadAllBytes($profilesFile)
 Write-FixtureJson 'files\config\profiles.json' @{profiles=@(@{name='agentRoot';enabled=$true;authorized_by_user=$true;mode='read-write';root=$base})}
 Assert-Rejected 'DataRoot under Files root' 'profile-root-exclusion'
 Write-FixtureJson 'files\config\profiles.json' @{profiles=@(@{name='agentRoot';enabled=$true;authorized_by_user=$true;mode='read-write';root=(Join-Path $data 'files')})}
 Assert-Rejected 'Files root under DataRoot' 'profile-root-exclusion'
 [IO.File]::WriteAllBytes($profilesFile,$oldProfiles)
 $destination=Join-Path $data 'allowlist';[IO.Directory]::CreateDirectory($destination)|Out-Null
 Assert-Rejected 'existing enrollment never overwritten' 'no-overwrite'
 Remove-Item -LiteralPath $destination -Force
 $oldBundle=[IO.File]::ReadAllBytes($bundle)
 foreach ($case in @('private-backup-key','wrong-key-algorithm','wrong-bundle-placement')) {
  $doc=[Text.Encoding]::UTF8.GetString($oldBundle)|ConvertFrom-Json
  if ($case -ceq 'private-backup-key') {$doc.keys|Add-Member -NotePropertyName backup -NotePropertyValue @{algorithm='AES256';private_key='NOT_A_KEY'}}
  if ($case -ceq 'wrong-key-algorithm') {$doc.keys.transport.algorithm='AES256'}
  if ($case -ceq 'wrong-bundle-placement') {$doc.placement.target_profile_id='other'}
  [IO.File]::WriteAllText($bundle,($doc|ConvertTo-Json -Depth 12 -Compress),[Text.UTF8Encoding]::new($false))
  $changed=$params.Clone();$changed.BundleSha256=(Get-FileHash -LiteralPath $bundle -Algorithm SHA256).Hash.ToLowerInvariant()
  Assert-Rejected $case 'pure-planner' $changed
 }
 [IO.File]::WriteAllBytes($bundle,$oldBundle)
 $sid=[Security.Principal.WindowsIdentity]::GetCurrent().User
 foreach ($case in @(@{Path=$data;Name='permissive DataRoot ACL';Stage='private-acl'},@{Path=(Join-Path $data 'files\config');Name='permissive private ancestor ACL';Stage='profile-root-exclusion'})) {
  $badAcl=[Security.AccessControl.DirectorySecurity]::new();$badAcl.SetOwner($sid);$badAcl.SetAccessRuleProtection($true,$false)
  $badAcl.AddAccessRule([Security.AccessControl.FileSystemAccessRule]::new($sid,'FullControl','ContainerInherit,ObjectInherit','None','Allow'))
  $everyone=[Security.AccessControl.FileSystemAccessRule]::new([Security.Principal.SecurityIdentifier]::new('S-1-1-0'),'Read','ContainerInherit,ObjectInherit','None','Allow')
  $badAcl.AddAccessRule($everyone)
  # Persist only modified owner/DACL sections: Set-Acl also requests SACL privilege here.
  # Both the permissive fixture and its restoration stay inside this disposable root.
  try {
   [IO.FileSystemAclExtensions]::SetAccessControl([IO.DirectoryInfo]::new($case.Path),$badAcl)
   $actual=Get-Acl -LiteralPath $case.Path
   $broad=@($actual.GetAccessRules($true,$true,[Security.Principal.SecurityIdentifier]) | Where-Object {$_.IdentityReference.Value -ceq 'S-1-1-0' -and $_.AccessControlType -eq 'Allow'})
   if ($broad.Count -ne 1 -or -not $actual.AreAccessRulesProtected) {throw 'ASSERT: permissive fixture DACL was not persisted'}
   Assert-Rejected $case.Name $case.Stage
  } finally {
   $badAcl.RemoveAccessRuleSpecific($everyone)
   [IO.FileSystemAclExtensions]::SetAccessControl([IO.DirectoryInfo]::new($case.Path),$badAcl)
   Assert-ZagentOwnerAcl $case.Path
  }
 }
 $junction=Join-Path $base 'linked-private';New-Item -ItemType Junction -Path $junction -Target $data|Out-Null
 try {$changed=$params.Clone();$changed.DataRoot=$junction;Assert-Rejected 'reparse DataRoot' 'paths' $changed} finally {Remove-Item -LiteralPath $junction -Force}
 $before=Get-FixtureSnapshot;$null=& $helper @params -PlanOnly
 if ((Get-FixtureSnapshot) -cne $before) {throw 'ASSERT: final plan invariance'}
 $script:passed++;Write-Output 'PASS final plan after rejected fixtures'
 # Load only the storage primitive AST, never bypass the actual entrypoint console guard.
 $tokens=$null;$errors=$null
 $ast=[Management.Automation.Language.Parser]::ParseFile($helper,[ref]$tokens,[ref]$errors)
 if ($errors.Count -ne 0) {throw 'ASSERT: helper parser errors'}
 $writer=@($ast.FindAll({param($node) $node -is [Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -ceq 'Publish-ZagentBootstrapCandidate'},$false))
 if ($writer.Count -ne 1) {throw 'ASSERT: secure bootstrap publication primitive missing'}
 . ([scriptblock]::Create($writer[0].Extent.Text))
 . (Join-Path $repo 'packaging\scripts\Owner-PrivateConfig.ps1')
 $store=Join-Path $base 'publication-fixture';New-ZagentPrivateDirectory $store
 $source=Join-Path $store 'source.json';[IO.File]::WriteAllText($source,'{}')
 $snapshots=@(@{Path=$source;Bytes=[IO.File]::ReadAllBytes($source)})
 function Invoke-FixtureBootstrapPython([string]$Code,$InputValue) {
  $start=[Diagnostics.ProcessStartInfo]::new();$start.FileName=$PythonExecutable;$start.UseShellExecute=$false;$start.CreateNoWindow=$true
  $start.WorkingDirectory=$repo;$start.Environment['PYTHONPATH']=(Join-Path $repo 'agents\files\engine');$start.Environment['PYTHONDONTWRITEBYTECODE']='1'
  foreach ($arg in @('-B','-c',$Code)) {$start.ArgumentList.Add($arg)}
  $start.RedirectStandardInput=$true;$start.RedirectStandardOutput=$true;$start.RedirectStandardError=$true
  $process=[Diagnostics.Process]::new();$process.StartInfo=$start
  try {
   if (-not $process.Start()) {throw 'ASSERT: fixture Python start'}
   $stdout=$process.StandardOutput.ReadToEndAsync();$stderr=$process.StandardError.ReadToEndAsync()
   $process.StandardInput.Write(($InputValue|ConvertTo-Json -Depth 12 -Compress));$process.StandardInput.Close()
   if (-not $process.WaitForExit(30000)) {$process.Kill($true);throw 'ASSERT: fixture Python timeout'}
   $out=$stdout.GetAwaiter().GetResult();$err=$stderr.GetAwaiter().GetResult()
   if ($process.ExitCode -ne 0 -or $err -or $out.Length -gt 65536) {throw ('ASSERT: real Python fixture failed: '+$err)}
   return $out
  } finally {$process.Dispose()}
 }
 foreach ($name in @('policy.json','profiles.json')) {
  $original='files\config\remote_execution_policy.json';if ($name -ceq 'profiles.json') {$original='files\config\profiles.json'}
  $path=Join-Path $store $name;[IO.File]::WriteAllBytes($path,[IO.File]::ReadAllBytes((Join-Path $data $original)))
  $snapshots+=@{Path=$path;Bytes=[IO.File]::ReadAllBytes($path)}
 }
 $code=@'
import sys,json
from pathlib import Path
from app.allowlist import bootstrap as b,protocol as p
from app.allowlist.owner_loader import process_sid
x=json.load(sys.stdin);root=Path(x['root']);raw=Path(x['bundle']).read_bytes()
print(json.dumps(b.plan(raw,acknowledged_sha256=x['ack'],placement=p.loads(raw)['placement'],data_root=str(root),policy_path=str(root/'policy.json'),profiles_path=str(root/'profiles.json'),owner_sid=process_sid(),expires_at=x['expiry'])))
'@
 $realPlan=(Invoke-FixtureBootstrapPython $code @{root=$store;bundle=$bundle;ack=$ack;expiry=$grant.expires_at})|ConvertFrom-Json
 $files=[ordered]@{}
 foreach ($property in $realPlan.files.PSObject.Properties) {
  $encoded=$property.Value.Replace('-','+').Replace('_','/');$encoded+='='*((4-$encoded.Length%4)%4)
  $files[$property.Name]=[Convert]::FromBase64String($encoded)
 }
 Publish-ZagentBootstrapCandidate -DataRoot $store -Files $files -Snapshots $snapshots
 $published=Join-Path $store 'allowlist'
 foreach ($name in $files.Keys) {
  $path=Join-Path $published $name;Assert-ZagentOwnerAcl $path
  if ([Convert]::ToBase64String([IO.File]::ReadAllBytes($path)) -cne [Convert]::ToBase64String($files[$name])) {throw 'ASSERT: published bytes differ'}
 }
 foreach ($name in @('','journal','replay')) {Assert-ZagentOwnerAcl (Join-Path $published $name)}
 if (@(Get-ChildItem -LiteralPath $store -Filter '.allowlist-stage-*' -Force).Count -ne 0) {throw 'ASSERT: stage left behind'}
 $script:passed++;Write-Output 'PASS real Windows publication primitive; exact bytes; protected owner ACL; clean staging'
 $code=@'
import sys,json
from pathlib import Path
from app.allowlist import bootstrap as b,protocol as p
from app.allowlist.owner_loader import load_owner
root=Path(json.load(sys.stdin)['root'])
manifest=p.loads((root/'allowlist'/'owner.json').read_bytes())
try:
    loaded=load_owner(b.configuration(manifest),oauth_current=lambda _:False,resolve_runtime=lambda _:None)
except PermissionError:
    # Disposable fixture only: reveal the underlying read-only loader assertion.
    from app.allowlist.owner_loader import LoadedOwner
    LoadedOwner(b.configuration(manifest),oauth_current=lambda _:False,resolve_runtime=lambda _:None)
    raise
assert loaded.config.capability_revision==p.loads((root/'allowlist'/'capability.json').read_bytes())['capability_revision']
assert manifest['mutations_ready'] is False
assert not list((root/'allowlist'/'journal').iterdir())
assert not list((root/'allowlist'/'replay').iterdir())
print('FIXTURE_OWNER_LOADER_PASS')
'@
 if ((Invoke-FixtureBootstrapPython $code @{root=$store}).Trim() -cne 'FIXTURE_OWNER_LOADER_PASS') {throw 'ASSERT: real owner loader result'}
 $script:passed++;Write-Output 'PASS real planner -> Windows publisher -> native owner loader; authority callbacks deny; inactive'
 function Assert-PublicationRejected([string]$Name,[string]$Expected,[Collections.IDictionary]$Artifacts=$files,[array]$Sources=$snapshots,[string]$Root=$store) {
  $before=Get-FixtureSnapshot;$caught=$false
  try {Publish-ZagentBootstrapCandidate -DataRoot $Root -Files $Artifacts -Snapshots $Sources} catch {
   if ($_.Exception.Message -notlike ('*'+$Expected+'*')) {throw ('ASSERT: wrong writer rejection for '+$Name+': '+$_.Exception.Message)};$caught=$true
  }
  if (-not $caught -or (Get-FixtureSnapshot) -cne $before) {throw ('ASSERT: publication accepted or changed fixture: '+$Name)}
  $script:passed++;Write-Output ('PASS publication rejects '+$Name+'; unchanged bytes')
 }
 Assert-PublicationRejected 'existing destination' 'Enrollment exists'
 Remove-Item -LiteralPath $published -Recurse -Force
 [IO.File]::WriteAllText($source,'changed')
 Assert-PublicationRejected 'stale source CAS' 'Source CAS conflict'
 [IO.File]::WriteAllBytes($source,$snapshots[0].Bytes)
 $badFiles=[ordered]@{};foreach ($name in $files.Keys) {$badFiles[$name]=$files[$name]};$badFiles['..\escaped.pub']=[byte[]]@(1)
 Assert-PublicationRejected 'traversal artifact' 'Invalid publication shape' $badFiles
 $badFiles.Remove('..\escaped.pub');$badFiles['approval.pub']=[byte[]]::new(65537)
 Assert-PublicationRejected 'oversize artifact' 'Invalid bounded artifact' $badFiles
 $lockPath=Join-Path $store '.allowlist-bootstrap.lock'
 $before=Get-FixtureSnapshot;$caught=$false
 $start=[Diagnostics.ProcessStartInfo]::new();$start.FileName=$PythonExecutable;$start.UseShellExecute=$false;$start.CreateNoWindow=$true
 foreach ($arg in @('-B','-c',"import sys; f=open(sys.argv[1],'rb'); print('READY',flush=True); sys.stdin.readline(); f.close()",$lockPath)) {$start.ArgumentList.Add($arg)}
 $start.RedirectStandardInput=$true;$start.RedirectStandardOutput=$true;$start.RedirectStandardError=$true
 $child=[Diagnostics.Process]::new();$child.StartInfo=$start
 try {
  if (-not $child.Start()) {throw 'ASSERT: native lock child start'}
  $ready=$child.StandardOutput.ReadLineAsync()
  if (-not $ready.Wait(5000) -or $ready.Result -cne 'READY') {throw 'ASSERT: native lock child readiness'}
  try {Publish-ZagentBootstrapCandidate -DataRoot $store -Files $files -Snapshots $snapshots} catch {
   if ($_.Exception.Message -notlike '*being used*') {throw};$caught=$true
  }
 } finally {
  if (-not $child.HasExited) {$child.StandardInput.WriteLine('release');$child.StandardInput.Close();if (-not $child.WaitForExit(5000)) {$child.Kill($true)}}
  $child.Dispose()
 }
 if (-not $caught -or (Get-FixtureSnapshot) -cne $before) {throw 'ASSERT: native second-process writer lock failure'}
 $script:passed++;Write-Output 'PASS publication rejects native second-process writer lock; unchanged bytes'
 $alias=Join-Path $base 'publication-junction';New-Item -ItemType Junction -Path $alias -Target $store|Out-Null
 try {Assert-PublicationRejected 'reparse publication root' 'Reparse path' $files $snapshots $alias} finally {Remove-Item -LiteralPath $alias -Force}
 if (Test-Path -LiteralPath $published) {throw 'ASSERT: rejected writer created enrollment'}
 $unsafeParent=Join-Path $base 'unsafe-publication-ancestor';New-ZagentPrivateDirectory $unsafeParent
 $unsafeRoot=Join-Path $unsafeParent 'private-child';New-ZagentPrivateDirectory $unsafeRoot
 $unsafeSource=Join-Path $unsafeRoot 'source.json';[IO.File]::WriteAllText($unsafeSource,'{}')
 $unsafeAcl=[Security.AccessControl.DirectorySecurity]::new();$unsafeAcl.SetOwner($sid);$unsafeAcl.SetAccessRuleProtection($true,$false)
 $unsafeAcl.AddAccessRule([Security.AccessControl.FileSystemAccessRule]::new($sid,'FullControl','ContainerInherit,ObjectInherit','None','Allow'))
 $unsafeAcl.AddAccessRule([Security.AccessControl.FileSystemAccessRule]::new([Security.Principal.SecurityIdentifier]::new('S-1-1-0'),'Modify','None','None','Allow'))
 [IO.FileSystemAclExtensions]::SetAccessControl([IO.DirectoryInfo]::new($unsafeParent),$unsafeAcl)
 Assert-PublicationRejected 'untrusted writable ancestor above private root' 'Unsafe publication ancestor' $files @(@{Path=$unsafeSource;Bytes=[IO.File]::ReadAllBytes($unsafeSource)}) $unsafeRoot
 foreach ($snapshot in $snapshots) {
  if ([Convert]::ToBase64String([IO.File]::ReadAllBytes($snapshot.Path)) -cne [Convert]::ToBase64String($snapshot.Bytes)) {throw 'ASSERT: publication changed source bytes'}
 }
 Write-Output ('PASS TOTAL='+$script:passed+'; installed state NOT_READ/NOT_WRITTEN; production enrollment NOT_RUN')
} finally {
 Remove-Item -LiteralPath $base -Recurse -Force
 if (Test-Path -LiteralPath $base) {throw 'ASSERT: fixture cleanup failed'}
}

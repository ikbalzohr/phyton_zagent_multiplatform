[CmdletBinding()]
param()
$ErrorActionPreference='Stop'
if ($env:OS -ne 'Windows_NT') { throw 'WINDOWS_ONLY; NOT_RUN' }
. (Join-Path $PSScriptRoot 'WindowsDashboard-Provisioning.ps1')
. (Join-Path $PSScriptRoot 'Owner-PrivateConfig.ps1')
. (Join-Path $PSScriptRoot 'ProfileAdministrationBootstrap.ps1')
function Assert-Fixture([bool]$Condition,[string]$Label) { if (-not $Condition) { throw ('Fixture assertion: '+$Label) } }
function Assert-FixtureDeny([scriptblock]$Action,[string]$Label) {
    $denied=$false; try { & $Action | Out-Null } catch { $denied=$true }
    Assert-Fixture $denied ('must deny '+$Label)
}
$now=[DateTimeOffset]::UtcNow.ToUnixTimeSeconds()
$fixture=@{resource_server=@{workspace_id='fixture-workspace';issuer='https://fixture.invalid';policy_revision='keep-revision';grants=@{
    'fixture-principal'=@{revoked=$false;expires_at=($now+3600);scopes=@('files:read','files:write');tools=@('files_read');
        untouched=@{marker='preserve';number=9007199254740993L};
        files_resource=@{kind='files';revoked=$false;resource_id='fixture-resource';profile_id='_-fixture';allowed_profile_ids=@('_-fixture');device_id='fixture-device';installation_id='fixture-installation'}};
    'other-principal'=@{revoked=$false;expires_at=($now+3600);scopes=@('files:read');tools=@('files_read')}
}};tool_policy=@{files_read=@{scope='files:read'}};unrelated=@{number=9007199254740993L}}
$before=$utf8.GetBytes((ConvertTo-Json -InputObject $fixture -Depth 32 -Compress))
$next=New-ProfileAdministrationPlan $before 'fixture-principal' 'fixture-workspace' 'fixture-device' 'fixture-installation' $now
$result=(Read-StrictJson $next).Object
Assert-Fixture ($result.resource_server.grants.'fixture-principal'.profile_management.actions.Count -eq 6) 'exact six actions'
Assert-Fixture ($result.resource_server.grants.'fixture-principal'.tools.Count -eq 7) 'six tools added'
Assert-Fixture ($null -eq $result.tool_policy.PSObject.Properties['files_profile_catalog_snapshot']) 'catalog never public policy'
foreach ($path in @(@('resource_server','grants','fixture-principal','expires_at'),@('resource_server','grants','fixture-principal','revoked'),
    @('resource_server','grants','fixture-principal','scopes'),@('resource_server','grants','fixture-principal','files_resource'),
    @('resource_server','grants','fixture-principal','untouched'),@('resource_server','grants','other-principal'),@('unrelated'))) {
    $a=Get-ProfileAdminSpan ($utf8.GetString($before)) $path; $b=Get-ProfileAdminSpan ($utf8.GetString($next)) $path
    Assert-Fixture (($utf8.GetString($before)).Substring($a.Start,$a.Length) -ceq ($utf8.GetString($next)).Substring($b.Start,$b.Length)) 'untouched JSON token preserved'
}
$again=New-ProfileAdministrationPlan $next 'fixture-principal' 'fixture-workspace' 'fixture-device' 'fixture-installation' $now
Assert-Fixture ([Convert]::ToBase64String($again) -ceq [Convert]::ToBase64String($next)) 'plan idempotent'
Assert-FixtureDeny { New-ProfileAdministrationPlan $before 'missing' 'fixture-workspace' 'fixture-device' 'fixture-installation' $now } 'wrong principal'
Assert-FixtureDeny { New-ProfileAdministrationPlan $before 'fixture-principal' 'wrong' 'fixture-device' 'fixture-installation' $now } 'workspace'
Assert-FixtureDeny { New-ProfileAdministrationPlan $before 'fixture-principal' 'fixture-workspace' 'other-device' 'fixture-installation' $now } 'device'
Assert-FixtureDeny { New-ProfileAdministrationPlan $before 'fixture-principal' 'fixture-workspace' 'fixture-device' 'fixture-installation' ($now+3600) } 'expiry no renewal'
foreach ($kind in @('revoked','scopes','resource-revoked','capability-unknown')) {
    $broken=(Read-StrictJson $before).Object; $grant=$broken.resource_server.grants.'fixture-principal'
    switch ($kind) {
        'revoked' {$grant.revoked=$true}
        'scopes' {$grant.scopes=@('files:write')}
        'resource-revoked' {$grant.files_resource.revoked=$true}
        'capability-unknown' {$grant | Add-Member -NotePropertyName profile_management -NotePropertyValue @{enabled=$true;unknown=$true}}
    }
    $bad=$utf8.GetBytes((ConvertTo-Json -InputObject $broken -Depth 32 -Compress))
    Assert-FixtureDeny { New-ProfileAdministrationPlan $bad 'fixture-principal' 'fixture-workspace' 'fixture-device' 'fixture-installation' $now } $kind
}
# JSON collection comparisons in PowerShell must never stand in for scalar type checks.
foreach ($path in @(
    'resource_server.workspace_id',
    'resource_server.grants.fixture-principal.files_resource.kind',
    'resource_server.grants.fixture-principal.files_resource.device_id',
    'resource_server.grants.fixture-principal.files_resource.installation_id',
    'resource_server.grants.fixture-principal.files_resource.profile_id',
    'resource_server.grants.fixture-principal.profile_management.workspace_id',
    'resource_server.grants.fixture-principal.profile_management.device_id',
    'resource_server.grants.fixture-principal.profile_management.installation_id',
    'tool_policy.files_profile_admin_create.scope')) {
    $parts = $path.Split('.')
    $good = (Read-StrictJson $next).Object
    foreach ($part in $parts) { $good = $good.PSObject.Properties[$part].Value }
    $matchingArray = ConvertTo-Json -InputObject @($good) -Compress
    foreach ($token in @('[]','null','true','{}',$matchingArray)) {
        $broken = (Read-StrictJson $next).Object; $parent = $broken
        for ($i=0; $i -lt ($parts.Count-1); $i++) { $parent = $parent.PSObject.Properties[$parts[$i]].Value }
        $parent.PSObject.Properties[$parts[-1]].Value = (ConvertFrom-Json ('{"value":'+$token+'}')).value
        $bad = $utf8.GetBytes((ConvertTo-Json -InputObject $broken -Depth 32 -Compress))
        Assert-FixtureDeny { New-ProfileAdministrationPlan $bad 'fixture-principal' 'fixture-workspace' 'fixture-device' 'fixture-installation' $now } ('scalar type '+$path+' '+$token)
    }
}
Assert-FixtureDeny { Read-StrictJson ($utf8.GetBytes('{"x":1,"x":2}')) } 'duplicate key'
Assert-FixtureDeny { Read-StrictJson ($utf8.GetBytes('{"x":NaN}')) } 'NaN'
# Exercise conservative stopped gate with fixture process metadata, without inspecting the host.
function Get-CimInstance { param($ClassName,$Filter); return @($script:fixtureProcesses) }
$script:fixtureProcesses=@(); Assert-ProfileAdminCoreStopped
foreach ($name in @('Zagent.Core.exe','dotnet.exe','dotnet')) {
    $script:fixtureProcesses=@([pscustomobject]@{Name=$name;ExecutablePath=$null})
    Assert-FixtureDeny { Assert-ProfileAdminCoreStopped } ('any process '+$name)
}
# Real disposable file/ACL/snapshot/backup/readback gate. The mocked process inventory
# is intentionally scoped to this fixture; the deployment helper itself always queries CIM.
$script:fixtureProcesses=@()
$fixtureRoot=Join-Path $env:LOCALAPPDATA ('Zagent-profile-admin-fixture-'+[guid]::NewGuid().ToString('N'))
New-ZagentPrivateDirectory $fixtureRoot
$install=Join-Path $fixtureRoot 'install'; $data=Join-Path $fixtureRoot 'data'
foreach ($directory in @($install,$data,(Join-Path $data 'config'),(Join-Path $data 'tunnel'),(Join-Path $data 'tunnel\config'),(Join-Path $data 'files'),(Join-Path $data 'files\config'))) { New-ZagentPrivateDirectory $directory }
$machinePath=Join-Path $data 'config\zagent.machine.json'
$target=Join-Path $data 'tunnel\config\tunnel.json'
$profiles=Join-Path $data 'files\config\profiles.json'
[IO.File]::WriteAllBytes($machinePath,$utf8.GetBytes((ConvertTo-Json -InputObject @{install_root=$install;data_root=$data} -Compress)))
[IO.File]::WriteAllBytes($target,$before)
$marker=$utf8.GetBytes('{"fixture_marker":"must-not-change"}')
[IO.File]::WriteAllBytes($profiles,$marker)
foreach ($file in @($machinePath,$target,$profiles)) { Set-ZagentOwnerAcl $file }
& (Join-Path $PSScriptRoot 'Enable-OwnerProfileAdministration.ps1') -InstallRoot $install -DataRoot $data -OwnerPrincipal 'fixture-principal' -WorkspaceId 'fixture-workspace' -DeviceId 'fixture-device' -InstallationId 'fixture-installation'
Assert-SnapshotUnchanged $target $next
Assert-SnapshotUnchanged $profiles $marker
$backups=@(Get-ChildItem -LiteralPath (Split-Path -Parent $target) -Filter '*.bak')
Assert-Fixture ($backups.Count -eq 1) 'exact one private independent backup'
Assert-SnapshotUnchanged $backups[0].FullName $before
Assert-MigrationPrivatePath $target
Assert-MigrationPrivatePath $backups[0].FullName
& (Join-Path $PSScriptRoot 'Enable-OwnerProfileAdministration.ps1') -InstallRoot $install -DataRoot $data -OwnerPrincipal 'fixture-principal' -WorkspaceId 'fixture-workspace' -DeviceId 'fixture-device' -InstallationId 'fixture-installation'
Assert-Fixture (@(Get-ChildItem -LiteralPath (Split-Path -Parent $target) -Filter '*.bak').Count -eq 1) 'no-op creates no backup'
Assert-FixtureDeny { Assert-SnapshotUnchanged $target $before } 'stale snapshot'
$script:fixtureProcesses=@([pscustomobject]@{Name='dotnet.exe'})
Assert-FixtureDeny { & (Join-Path $PSScriptRoot 'Enable-OwnerProfileAdministration.ps1') -InstallRoot $install -DataRoot $data -OwnerPrincipal 'fixture-principal' -WorkspaceId 'fixture-workspace' -DeviceId 'fixture-device' -InstallationId 'fixture-installation' } 'entry denies ambiguous host before write'
Assert-SnapshotUnchanged $target $next
Remove-Item Function:\Get-CimInstance
Write-Output ('PASS profile administration plan/preservation/denial/private-file fixtures; fixture evidence='+$fixtureRoot+'; installation NOT_APPLIED')

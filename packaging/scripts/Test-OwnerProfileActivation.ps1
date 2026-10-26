[CmdletBinding()]
param()
# Windows-only disposable behavioral fixtures. No product imports/processes, no
# production DataRoot, no credentials. Retain uniquely-owned evidence; no cleanup.
$ErrorActionPreference = 'Stop'
foreach ($name in @('Owner-ProfileActivation.ps1','Activate-OwnerFilesProfile.ps1','Test-OwnerProfileActivation.ps1')) {
    $tokens = $null; $errors = $null
    $null = [Management.Automation.Language.Parser]::ParseFile((Join-Path $PSScriptRoot $name), [ref]$tokens, [ref]$errors)
    if (@($errors).Count) { throw ('PowerShell parser failure: ' + $name + ': ' + (($errors | ForEach-Object Message) -join '; ')) }
}
. (Join-Path $PSScriptRoot 'WindowsDashboard-Provisioning.ps1')
. (Join-Path $PSScriptRoot 'Owner-PrivateConfig.ps1')
. (Join-Path $PSScriptRoot 'Owner-ProfileActivation.ps1')
Assert-ZagentOwnerConsole
$base = Join-Path ([IO.Path]::GetTempPath()) ('zagent-profile-fixture-' + [guid]::NewGuid().ToString('N'))
New-ZagentPrivateDirectory $base
$InstallRoot = Join-Path $base 'install'
New-ZagentPrivateDirectory $InstallRoot
$data = Join-Path $base 'data'
New-ZagentPrivateDirectory $data
$root = Join-Path $base 'agentRoot'; New-ZagentPrivateDirectory $root
$old = Join-Path $root 'legacy-workspace'; New-ZagentPrivateDirectory $old
$other = Join-Path $base 'other'; New-ZagentPrivateDirectory $other
$marker = Join-Path $old 'physical-data-marker.bin'
$markerBytes = [byte[]]@(0, 19, 255, 13, 10, 77)
[IO.File]::WriteAllBytes($marker, $markerBytes)
$exe = Join-Path ([Environment]::SystemDirectory) 'WindowsPowerShell\v1.0\powershell.exe'
Assert-ActivationPath $exe -Executable
function Assert-Fixture($Condition, [string]$Message) { if (-not $Condition) { throw ('FIXTURE FAILED: ' + $Message) } }
function Expect-Refusal([scriptblock]$Action, [string]$Label) {
    $failed = $false
    try { & $Action | Out-Null } catch { $failed = $true }
    Assert-Fixture $failed ('expected refusal: ' + $Label)
    Write-Host ('PASS denial: ' + $Label)
}
$principal = 'principal_v1_41d40891edc920d08c8bf7d58f508bb1a082a9dc8dc5bb70f4fa2d913161a59d'
$profiles = [ordered]@{ schema_version = '2.0'; active_profile = 'appBridge'; profiles = @(
    [ordered]@{ name = 'appBridge'; root = $old; mode = 'read-write'; enabled = $true; authorized_by_user = $true },
    [ordered]@{ name = 'agentRoot'; root = $root; mode = 'read-write'; enabled = $true; authorized_by_user = $true },
    [ordered]@{ name = 'other'; root = $other; mode = 'read-write'; enabled = $true; authorized_by_user = $true }
) }
$policy = [ordered]@{ version = 1; enabled = $true; execution_mode = 'owner-account'; acknowledge_host_access = $true;
    profile_id = 'appBridge'; root = $old; allowed_tools = @('files_exec_command'); allowed_executables = @($exe); max_timeout_seconds = 37; max_output_chars = 1234 }
$grant = [ordered]@{ revoked = $false; expires_at = 1793539666; tools = @('files_stat','files_exec_command'); scopes = @('files:read','files:write','files:execute'); files_resource = [ordered]@{
    kind = 'files'; profile_id = 'appBridge'; resource_id = 'workspace:workspace-local:approved-repository'; revoked = $false;
    device_id = '7338141d-ab55-4d78-a97e-35336f970fb5'; installation_id = '7c82db6b-f6f2-4072-bd38-7ed763aa45d3'; allowed_profile_ids = @('appBridge','other') } }
$tunnel = [ordered]@{ resource_server = [ordered]@{ issuer = 'https://vmi3669591.contaboserver.net/realms/zagent'; resource_uri = 'https://zagent.ikbalzohr.web.id/mcp'; workspace_id = 'workspace-local'; introspection_client_id = 'zagent-resource-server'; introspection_endpoint = 'https://vmi3669591.contaboserver.net/realms/zagent/protocol/openid-connect/token/introspect'; grants = [ordered]@{} }; untouched = 'sentinel' }
$tunnel.resource_server.grants[$principal] = $grant
$pBytes = $utf8.GetBytes((ConvertTo-ActivationToken $profiles))
$cBytes = $utf8.GetBytes((ConvertTo-ActivationToken $policy))
# Deliberately include numeric lexemes that ConvertFrom/To-Json must NOT round.
$tText = (ConvertTo-ActivationToken $tunnel).Insert(1, '"precise":9007199254740993123,"exponent":1.2300e+09,')
$tBytes = $utf8.GetBytes($tText)
$plan = New-OwnerProfileActivationPlan $pBytes $cBytes $tBytes $root $old
$nextP = (Read-StrictJson $plan.Profiles).Object
$nextC = (Read-StrictJson $plan.Commands).Object
$nextT = (Read-StrictJson $plan.Grant).Object
Assert-Fixture ($nextP.active_profile -ceq 'agentRoot') 'actual active_profile default'
Assert-Fixture (@($nextP.profiles | Where-Object name -CEQ 'appBridge').Count -eq 0) 'appBridge row removed'
Assert-Fixture ($nextP.profiles.Count -eq 2) 'unrelated profile preserved'
Assert-Fixture ($null -eq $nextC.profiles.PSObject.Properties['appBridge']) 'legacy command entry removed'
Assert-Fixture ($nextC.version -eq 2 -and @($nextC.PSObject.Properties).Count -eq 2) 'exact v2 envelope'
Assert-Fixture ($nextC.profiles.agentRoot.root -ceq $root -and $nextC.profiles.agentRoot.allowed_executables[0] -ceq $exe -and $nextC.profiles.agentRoot.max_timeout_seconds -eq 37) 'reuse exact executable and limits'
$b = $nextT.resource_server.grants.$principal.files_resource
Assert-Fixture ($b.profile_id -ceq 'agentRoot' -and $b.allowed_profile_ids.Count -eq 1 -and $b.allowed_profile_ids[0] -ceq 'agentRoot') 'default allowlist is NOT all local approvals'
$bp = @('resource_server','grants',$principal,'files_resource')
$reversed = Replace-ActivationToken ($utf8.GetString($plan.Grant)) ($bp + @('profile_id')) '"appBridge"'
$reversed = Replace-ActivationToken $reversed ($bp + @('allowed_profile_ids')) '["appBridge","other"]'
Assert-Fixture ($reversed -ceq $tText) 'ALL unrelated tunnel bytes/expiry/revocation/tools/scopes/OAuth preserved'
Assert-Fixture ($nextT.resource_server.grants.$principal.expires_at -eq 1793539666) 'finite expiry preserved'
$again = New-OwnerProfileActivationPlan $plan.Profiles $plan.Commands $plan.Grant $root $old
foreach ($key in @('Profiles','Commands','Grant')) {
    Assert-Fixture ([Convert]::ToBase64String($again[$key]) -ceq [Convert]::ToBase64String($plan[$key])) 'already-current candidate is byte-identical'
}
$explicit = New-OwnerProfileActivationPlan $pBytes $cBytes $tBytes $root $old @('agentRoot','other')
Assert-Fixture (((Read-StrictJson $explicit.Grant).Object.resource_server.grants.$principal.files_resource.allowed_profile_ids).Count -eq 2) 'explicit optional approved profiles'
$readOnly = Replace-ActivationToken ($utf8.GetString($pBytes)) @('profiles','2','mode') '"read-only"'
$readOnlyPlan = New-OwnerProfileActivationPlan ($utf8.GetBytes($readOnly)) $cBytes $tBytes $root $old @('agentRoot','other')
Assert-Fixture (((Read-StrictJson $readOnlyPlan.Profiles).Object.profiles[1].mode) -ceq 'read-only') 'optional approved read-only profile is not upgraded'
# Absence of preexisting allowlist is supported, not permission to grant all.
$noAllow = $tText.Replace(',"allowed_profile_ids":["appBridge","other"]','')
$inserted = New-OwnerProfileActivationPlan $pBytes $cBytes ($utf8.GetBytes($noAllow)) $root $old
Assert-Fixture (((Read-StrictJson $inserted.Grant).Object.resource_server.grants.$principal.files_resource.allowed_profile_ids).Count -eq 1) 'insert missing allowlist'
foreach ($list in @(@('agentRoot','*'), @('agentRoot','appBridge'), @('other'), @('agentRoot','agentRoot'), @('agentRoot','missing'))) {
    Expect-Refusal { New-OwnerProfileActivationPlan $pBytes $cBytes $tBytes $root $old $list } 'invalid/unapproved allowlist'
}
Expect-Refusal { New-OwnerProfileActivationPlan $pBytes $cBytes ($utf8.GetBytes($tText.Replace('"revoked":false','"revoked":true'))) $root $old } 'revoked'
Expect-Refusal { New-OwnerProfileActivationPlan $pBytes $cBytes ($utf8.GetBytes($tText.Replace('1793539666','1'))) $root $old } 'expired/no renewal'
Expect-Refusal { New-OwnerProfileActivationPlan ($utf8.GetBytes(($utf8.GetString($pBytes)).Replace('"authorized_by_user":true','"authorized_by_user":false'))) $cBytes $tBytes $root $old } 'unapproved agentRoot'
Expect-Refusal { New-OwnerProfileActivationPlan $pBytes $cBytes $tBytes $other $old } 'root mismatch'
Expect-Refusal { Read-StrictJson ($utf8.GetBytes('{"a":1,"A":2}')) } 'duplicate JSON names'
Expect-Refusal { Assert-ActivationPath ($exe.Replace('.exe','.cmd')) -Executable } 'no batch/alias expansion'
$junction = Join-Path $base 'reparse-profile'
New-Item -ItemType Junction -Path $junction -Target $old | Out-Null
Expect-Refusal { Assert-ActivationPath $junction } 'reparse root/ancestor'
$badAclPath = Join-Path $data 'bad-acl.json'
[IO.File]::WriteAllText($badAclPath, '{}'); Set-ZagentOwnerAcl $badAclPath
$acl = Get-Acl -LiteralPath $badAclPath
$unrelatedSid = [Security.Principal.SecurityIdentifier]::new([Security.Principal.WellKnownSidType]::AuthenticatedUserSid, $null)
$acl.AddAccessRule([Security.AccessControl.FileSystemAccessRule]::new($unrelatedSid, 'Read', 'Allow'))
Set-Acl -LiteralPath $badAclPath -AclObject $acl
Expect-Refusal { Read-BoundedBytes $badAclPath } 'unrelated ACL not adopted'
# V2 preservation: unrelated explicitly-approved policy remains byte-identical.
$otherPolicy = Replace-ActivationToken ($utf8.GetString($cBytes)) @('profile_id') '"other"'
$otherPolicy = Replace-ActivationToken $otherPolicy @('root') (ConvertTo-ActivationToken $other)
$v2 = '{"version":2,"profiles":{"appBridge":' + $utf8.GetString($cBytes) + ',"other":' + $otherPolicy + '}}'
$v2Plan = New-OwnerProfileActivationPlan $pBytes ($utf8.GetBytes($v2)) $tBytes $root $old
Assert-Fixture ((Get-ActivationToken ($utf8.GetString($v2Plan.Commands)) @('profiles','other')) -ceq $otherPolicy) 'preserve unrelated approved v1 policy'
# Real shared SID/ACL, bounded reads, snapshots, atomic filesystem replacements.
$script:fault = ''; $script:guardCount = 0; $script:targetGrant = ''; $script:caseDir = ''
# Fixture-only fault seam; production code has no injection parameter. Still run
# the real Find-Core each time; the isolated install is never started.
function Assert-CoreStopped {
    if (@(Find-Core).Count -ne 0) { throw 'Fixture Core unexpectedly running.' }
    $script:guardCount++
    if ($script:guardCount -eq 8 -and $script:fault -ceq 'concurrent') { [IO.File]::AppendAllText($script:targetGrant, ' ') }
    if ($script:guardCount -eq 8 -and $script:fault -ceq 'backup') {
        $bak = @(Get-ChildItem -LiteralPath $script:caseDir -Filter '*.bak')[0].FullName
        [IO.File]::AppendAllText($bak, ' ')
    }
    if ($script:guardCount -eq 9 -and $script:fault -ceq 'partial') { throw 'Fixture injected partial failure before command/grant write.' }
}
foreach ($scenario in @('success','concurrent','backup','partial')) {
    $case = Join-Path $data $scenario; New-ZagentPrivateDirectory $case
    $entries = @{}
    foreach ($name in @('profiles','commands','grant')) {
        $original = switch ($name) { profiles { $pBytes }; commands { $cBytes }; grant { $tBytes } }
        $candidate = switch ($name) { profiles { $plan.Profiles }; commands { $plan.Commands }; grant { $plan.Grant } }
        $path = Join-Path $case ($name + '.json')
        [IO.File]::WriteAllBytes($path, [byte[]]$original); Set-ZagentOwnerAcl $path
        $entries[$name] = @{ Path = $path; Before = [byte[]]$original; Next = [byte[]]$candidate }
    }
    $script:fault = $scenario; $script:guardCount = 0; $script:targetGrant = $entries.grant.Path; $script:caseDir = $case
    if ($scenario -ceq 'success') {
        Invoke-OwnerProfileActivationCommit $entries
        foreach ($name in @('profiles','commands','grant')) { Assert-SnapshotUnchanged $entries[$name].Path $entries[$name].Next }
    } else {
        Expect-Refusal { Invoke-OwnerProfileActivationCommit $entries } $scenario
        if ($scenario -ceq 'partial') { Assert-SnapshotUnchanged $entries.profiles.Path $entries.profiles.Next }
        else { Assert-SnapshotUnchanged $entries.profiles.Path $entries.profiles.Before }
        Assert-SnapshotUnchanged $entries.commands.Path $entries.commands.Before
        if ($scenario -cne 'concurrent') { Assert-SnapshotUnchanged $entries.grant.Path $entries.grant.Before }
    }
    Assert-Fixture (@(Get-ChildItem -LiteralPath $case -Filter '*.bak').Count -eq 3) 'ALL backups prepared before writes'
    Assert-Fixture ([Convert]::ToBase64String([IO.File]::ReadAllBytes($marker)) -ceq [Convert]::ToBase64String($markerBytes)) 'physical workspace marker untouched'
    Assert-Fixture (Test-Path -LiteralPath $old -PathType Container) 'physical legacy workspace still exists'
    Write-Host ('PASS disposable filesystem scenario: ' + $scenario)
}
Write-Host ('OWNER_PROFILE_WINDOWS_FIXTURES_PASS; evidence retained at ' + $base)
Write-Host 'Production activation NOT_APPLIED. No product process, identity, OAuth or production data was used.'

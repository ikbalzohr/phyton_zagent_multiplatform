param([string]$PlanOutput)
# Isolated pure PowerShell regression fixtures; no Windows ACL/enrollment claims.
# Runs on /opt/pwsh on the VPS; exercises the bounded pure-plan library only.
$ErrorActionPreference = 'Stop'
Remove-Module PSReadLine -Force -ErrorAction SilentlyContinue
Set-StrictMode -Version Latest
$scriptsDir = $PSScriptRoot
. (Join-Path $scriptsDir 'Owner-PrivateConfig.ps1')
. (Join-Path $scriptsDir 'ProfileAdministrationBootstrap.ps1')
. (Join-Path $scriptsDir 'Owner-CommandPolicyRebind.ps1')
$utf8 = [Text.UTF8Encoding]::new($false,$true)
$script:failures = 0
$script:checked = 0
function Check { param([scriptblock]$cond,[string]$label) $script:checked++; try { if (-not (& $cond)) { throw 'condition false' } } catch { $script:failures++; Write-Output ("FAIL: $label ($($_.Exception.Message))") } }
function J { param([object]$o) return (ConvertTo-Json -InputObject $o -Compress -Depth 8) }
# v1 single-document policy with preserved authority limits.
$policy = '{"version":1,"enabled":true,"execution_mode":"owner-account","acknowledge_host_access":true,"profile_id":"old","root":"D:\\old","allowed_tools":["files_exec_command"],"allowed_executables":["C:\\Tools\\python.exe"],"max_timeout_seconds":37,"max_output_chars":1234}'
# v1 policy whose own profile_id IS agentRoot (for the conflict-guard case).
$policyAgentRoot = '{"version":1,"enabled":true,"execution_mode":"owner-account","acknowledge_host_access":true,"profile_id":"agentRoot","root":"D:\\3-Ikbalzohr\\Agent","allowed_tools":["files_exec_command"],"allowed_executables":["C:\\Tools\\python.exe"],"max_timeout_seconds":37,"max_output_chars":1234}'
$profiles = '{"profiles":[{"name":"old","root":"D:\\old","enabled":true,"authorized_by_user":true,"mode":"read-write"},{"name":"agentRoot","root":"D:\\3-Ikbalzohr\\Agent","enabled":true,"authorized_by_user":true,"mode":"read-write"}]}'
$plan = New-OwnerCommandPolicyRebindPlan ($utf8.GetBytes($policy)) ($utf8.GetBytes($profiles)) 'old' 'D:\old'
$check = Read-StrictJson $plan.Bytes
Check { $check.Object.profile_id -ceq 'agentRoot' } 'v1 profile_id updated'
Check { $check.Object.root -ceq 'D:\3-Ikbalzohr\Agent' } 'v1 root updated'
Check { $check.Object.version -eq 1 -and $check.Object.enabled -eq $true } 'v1 version/enabled preserved'
Check { $check.Object.acknowledge_host_access -eq $true -and $check.Object.execution_mode -ceq 'owner-account' } 'v1 host_access/mode preserved'
Check { $check.Object.allowed_tools -ceq @('files_exec_command') } 'v1 allowed_tools preserved'
Check { $check.Object.allowed_executables -ceq @('C:\Tools\python.exe') } 'v1 allowed_executables preserved'
Check { $check.Object.max_timeout_seconds -eq 37 } 'v1 max_timeout preserved'
Check { $check.Object.max_output_chars -eq 1234 } 'v1 max_output preserved'
$rev = $utf8.GetString($plan.Bytes).Replace('"agentRoot"','"old"').Replace('"D:\\3-Ikbalzohr\\Agent"','"D:\\old"')
Check { $rev -ceq $policy } 'v1 reverse edit reproduces original bytes'
Write-Output 'PASS v1 token-only rebind; all authority limits verified'
# RED: preexisting target conflicting policy (source already agentRoot) is refused.
$tc = $null
try { $tc = New-OwnerCommandPolicyRebindPlan ($utf8.GetBytes($policyAgentRoot)) ($utf8.GetBytes($profiles)) 'agentRoot' 'D:\3-Ikbalzohr\Agent' } catch { $tc = $_.Exception.Message }
Check { $null -ne $tc -and $tc -match 'Refusing preexisting target' } 'refuses preexisting agentRoot source conflict'
Write-Output 'PASS refuses preexisting agentRoot source conflict'
# v2 document: rebind source entry, sibling preserved verbatim.
$v2doc = @{version=2;profiles=@{old=@{version=1;enabled=$true;execution_mode='owner-account';acknowledge_host_access=$true;profile_id='old';root='D:\old';allowed_tools=@('files_exec_command');allowed_executables=@('C:\Tools\python.exe');max_timeout_seconds=37;max_output_chars=1234};sibling=@{version=1;enabled=$true;execution_mode='owner-account';acknowledge_host_access=$true;profile_id='sibling';root='D:\sibling';allowed_tools=@('files_stat');allowed_executables=@('C:\Tools\pwsh.exe');max_timeout_seconds=99;max_output_chars=500}}}
$v2 = J $v2doc
$plan2 = New-OwnerCommandPolicyRebindPlan ($utf8.GetBytes($v2)) ($utf8.GetBytes($profiles)) 'old' 'D:\old'
$chk2 = Read-StrictJson $plan2.Bytes
Check { $null -ne $chk2.Object.profiles.PSObject.Properties['agentRoot'] -and $null -eq $chk2.Object.profiles.PSObject.Properties['old'] -and $chk2.Object.profiles.agentRoot.profile_id -ceq 'agentRoot' -and $chk2.Object.profiles.agentRoot.root -ceq 'D:\3-Ikbalzohr\Agent' } 'v2 map key and embedded id both retargeted for real consumer'
Check { $chk2.Object.profiles.sibling.profile_id -ceq 'sibling' -and $chk2.Object.profiles.sibling.root -ceq 'D:\sibling' } 'v2 sibling profile_id/root preserved'
Check { $chk2.Object.profiles.sibling.max_timeout_seconds -eq 99 -and $chk2.Object.profiles.sibling.max_output_chars -eq 500 } 'v2 sibling limits preserved'
Check { $chk2.Object.profiles.sibling.allowed_tools -ceq @('files_stat') } 'v2 sibling allowed_tools preserved'
Write-Output 'PASS v2 sibling preservation + rebind'
# RED: v2 refuses if agentRoot already exists as a policy entry (internally consistent).
$v2conflict = J (@{version=2;profiles=@{old=$v2doc.profiles.old;agentRoot=@{version=1;enabled=$true;execution_mode='owner-account';acknowledge_host_access=$true;profile_id='agentRoot';root='D:\3-Ikbalzohr\Agent';allowed_tools=@('files_exec_command');allowed_executables=@('C:\Tools\python.exe');max_timeout_seconds=37;max_output_chars=1234}}})
$tc2 = $null
try { $tc2 = New-OwnerCommandPolicyRebindPlan ($utf8.GetBytes($v2conflict)) ($utf8.GetBytes($profiles)) 'old' 'D:\old' } catch { $tc2 = $_.Exception.Message }
Check { $null -ne $tc2 -and $tc2 -match 'already present in command policy' } 'v2 refuses preexisting agentRoot policy entry'
Write-Output 'PASS v2 preexisting agentRoot policy refusal'
# RED: source profile absent from profiles.json is refused.
$badProfiles = '{"profiles":[{"name":"agentRoot","root":"D:\\3-Ikbalzohr\\Agent","enabled":true,"authorized_by_user":true,"mode":"read-write"}]}'
$tc3 = $null
try { $tc3 = New-OwnerCommandPolicyRebindPlan ($utf8.GetBytes($policy)) ($utf8.GetBytes($badProfiles)) 'old' 'D:\old' } catch { $tc3 = $_.Exception.Message }
Check { $null -ne $tc3 -and $tc3 -match 'absent from local profiles' } 'refuses absent source profile in profiles.json'
# RED: source root mismatch (guessed binding) refused.
$tc4 = $null
try { $tc4 = New-OwnerCommandPolicyRebindPlan ($utf8.GetBytes($policy)) ($utf8.GetBytes($profiles)) 'old' 'D:\wrong-root' } catch { $tc4 = $_.Exception.Message }
Check { $null -ne $tc4 -and $tc4 -match 'Source root not supplied exactly|Source profile root mismatch' } 'refuses mismatched source root'
# RED: disabled source profile refused.
$disabledProfiles = '{"profiles":[{"name":"old","root":"D:\\old","enabled":false,"authorized_by_user":true,"mode":"read-write"}]}'
$tc5 = $null
try { $tc5 = New-OwnerCommandPolicyRebindPlan ($utf8.GetBytes($policy)) ($utf8.GetBytes($disabledProfiles)) 'old' 'D:\old' } catch { $tc5 = $_.Exception.Message }
Check { $null -ne $tc5 -and $tc5 -match 'not locally approved read-write' } 'refuses disabled source profile'
# RED: read-only source profile refused.
$roProfiles = '{"profiles":[{"name":"old","root":"D:\\old","enabled":true,"authorized_by_user":true,"mode":"read-only"}]}'
$tc6 = $null
try { $tc6 = New-OwnerCommandPolicyRebindPlan ($utf8.GetBytes($policy)) ($utf8.GetBytes($roProfiles)) 'old' 'D:\old' } catch { $tc6 = $_.Exception.Message }
Check { $null -ne $tc6 -and $tc6 -match 'not locally approved read-write' } 'refuses read-only source profile'
# An explicit owner migration may use the existing approved policy when its old catalog row was removed.
Check { $removedPlan = New-OwnerCommandPolicyRebindPlan ($utf8.GetBytes($policy)) ($utf8.GetBytes($badProfiles)) 'old' 'D:\old' -AllowRemovedSourceProfile; (Read-StrictJson $removedPlan.Bytes).Object.profile_id -ceq 'agentRoot' } 'explicit removed-source migration preserves existing command approval'
Check { $rejected=$false; try { $null=New-OwnerCommandPolicyRebindPlan ($utf8.GetBytes($policy.Replace('"enabled"','"ENABLED"'))) ($utf8.GetBytes($profiles)) 'old' 'D:\old' } catch { $rejected=$true }; $rejected } 'consumer exact-case policy keys required'
Check { $scriptText=Get-Content -LiteralPath (Join-Path $scriptsDir 'Rebind-OwnerCommandPolicy.ps1') -Raw; $scriptText -match 'Assert-ProfileAdminCoreStopped' -and $scriptText -notmatch '(?m)^Assert-CoreStopped' -and $scriptText -match 'zagent.machine.json' -and $scriptText -match 'machine.install_root' -and $scriptText -match 'Assert-SnapshotUnchanged \$machinePath \$machineBytes' } 'offline publisher checks all Core hosts and enrolled binding snapshot'
Check { $summary=@(Get-OwnerCommandPolicySummary ($utf8.GetBytes($policy))); $summary.Count -eq 1 -and $summary[0].profile_id -ceq 'old' -and $summary[0].root -ceq 'D:\old' -and $null -eq $summary[0].PSObject.Properties['token'] } 'inspection projects bounded policy fields only'
Check { $badVersion=$v2.Replace('"version":1','"version":true'); $rejected=$false; try { $null=New-OwnerCommandPolicyRebindPlan ($utf8.GetBytes($badVersion)) ($utf8.GetBytes($profiles)) 'old' 'D:\old' } catch { $rejected=$true }; $rejected } 'v2 rejects boolean member version like consumer'
Check { $sourceDisabled=$profiles.Replace('"name":"old","root":"D:\\old","enabled":true','"name":"old","root":"D:\\old","enabled":false'); $rejected=$false; try { $null=New-OwnerCommandPolicyRebindPlan ($utf8.GetBytes($policy)) ($utf8.GetBytes($sourceDisabled)) 'old' 'D:\old' -AllowRemovedSourceProfile } catch { $rejected=$true }; $rejected } 'removed-source switch never overrides existing disabled source'
if ($script:failures -ne 0) { Write-Output ("RESULT=FAIL checked=$script:checked failed=$script:failures"); exit 1 }
if ($PlanOutput) {
    [IO.File]::WriteAllText($PlanOutput, (ConvertTo-Json -Depth 12 -InputObject @{ v1=(Read-StrictJson $plan.Bytes).Object; v2=(Read-StrictJson $plan2.Bytes).Object; original_v1=(Read-StrictJson ($utf8.GetBytes($policy))).Object; original_v2=$v2doc }), $utf8)
}
Write-Output ("RESULT=PASS checked=$script:checked failed=0")
exit 0

# Explicit owner-local addition of the explicit portable .NET host; never apply via MCP shell.
[CmdletBinding(DefaultParameterSetName='Apply')]
param(
 [Parameter(Mandatory=$true)][string]$InstallRoot,
 [Parameter(Mandatory=$true,ParameterSetName='Apply')][string]$DataRoot,
 [Parameter(Mandatory=$true,ParameterSetName='Test')][switch]$SelfTest
)
$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
. (Join-Path $InstallRoot 'packaging/scripts/WindowsDashboard-Provisioning.ps1')
. (Join-Path $InstallRoot 'packaging/scripts/Owner-PrivateConfig.ps1')
. (Join-Path $InstallRoot 'packaging/scripts/ProfileAdministrationBootstrap.ps1')
. (Join-Path $InstallRoot 'packaging/scripts/Owner-CommandPolicyRebind.ps1')
$dotnet='D:\3-Ikbalzohr\Agent\appBridge\toolchain\dotnet10\dotnet.exe'
function New-OwnerDotnetPlan([byte[]]$Before) {
 $entries=@(Get-OwnerCommandPolicySummary $Before | Where-Object { $_.profile_id -ceq 'agentRoot' })
 if ($entries.Count -ne 1 -or -not (Test-TrueFlag $entries[0].enabled) -or -not (Test-TrueFlag $entries[0].acknowledge_host_access) -or $entries[0].execution_mode -cne 'owner-account' -or $entries[0].root.TrimEnd('\') -cne 'D:\3-Ikbalzohr\Agent') { throw 'Exactly one approved agentRoot command policy required.' }
 $list=$entries[0].allowed_executables
 if ($list -isnot [array] -or $list.Count -lt 1 -or $list.Count -gt 64 -or @($list | Where-Object { $_ -isnot [string] -or [string]::IsNullOrWhiteSpace($_) }).Count -gt 0) { throw 'Existing bounded executable allowlist required.' }
 $existing=@($list | Where-Object { $_ -ceq $dotnet })
 if ($existing.Count -gt 1) { throw 'Duplicate dotnet approval; no write.' }
 if ($existing.Count -eq 1) { return ,$Before }
 if ($list.Count -eq 64) { throw 'Executable allowlist capacity reached.' }
 $parsed=Read-StrictJson $Before
 $path=@('allowed_executables')
 if ($parsed.Object.version -eq 2) { $path=@('profiles','agentRoot','allowed_executables') }
 $span=Get-ProfileAdminSpan $parsed.Text $path
 $index=$span.Start+$span.Length-1
 if ($parsed.Text[$index] -ne ']') { throw 'Allowlist array token required.' }
 $addition=','+(ConvertTo-Json -InputObject $dotnet -Compress)
 $text=$parsed.Text.Insert($index,$addition)
 $next=$utf8.GetBytes($text)
 $null=Get-OwnerCommandPolicySummary $next
 if ($next.Length -gt 262144 -or $text.Remove($index,$addition.Length) -cne $parsed.Text) { throw 'Unrelated bytes changed or candidate exceeds bound.' }
 return ,$next
}
if ($SelfTest) {
 $entry=[ordered]@{version=1;enabled=$true;execution_mode='owner-account';acknowledge_host_access=$true;profile_id='agentRoot';root='D:\3-Ikbalzohr\Agent';allowed_tools=@('files_command_capabilities','files_build');allowed_executables=@('C:\Tools\git.exe');max_timeout_seconds=1800;max_output_chars=200000}
 $checked=0
 foreach ($v in @(1,2)) {
  $doc=$entry
  if ($v -eq 2) { $doc=@{version=2;profiles=@{agentRoot=$entry;sibling=@{version=1;enabled=$false;execution_mode='owner-account';acknowledge_host_access=$true;profile_id='sibling';root='D:\sibling';allowed_tools=@('files_exec_command');allowed_executables=@('C:\Tools\node.exe');max_timeout_seconds=11;max_output_chars=500}}} }
  $before=$utf8.GetBytes((ConvertTo-Json -Depth 12 -InputObject $doc))
  $next=New-OwnerDotnetPlan $before
  $a=(Read-StrictJson $before).Object; $b=(Read-StrictJson $next).Object
  if ($v -eq 2) {
   if ((ConvertTo-Json -Depth 8 -Compress -InputObject $a.profiles.sibling) -cne (ConvertTo-Json -Depth 8 -Compress -InputObject $b.profiles.sibling)) { throw 'Sibling changed.' }
   $a=$a.profiles.agentRoot; $b=$b.profiles.agentRoot
  }
  if (@($b.allowed_executables).Count -ne 2 -or $b.allowed_executables[0] -cne 'C:\Tools\git.exe' -or $b.allowed_executables[1] -cne $dotnet) { throw 'Incorrect exact allowlist addition.' }; $checked++
  $b.allowed_executables=$a.allowed_executables
  if ((ConvertTo-Json -Depth 8 -Compress -InputObject $a) -cne (ConvertTo-Json -Depth 8 -Compress -InputObject $b)) { throw 'Authority fields changed.' }; $checked++
  if ([Convert]::ToBase64String((New-OwnerDotnetPlan $next)) -cne [Convert]::ToBase64String($next)) { throw 'Repeated plan must be no-op.' }; $checked++
 }
 $entry.enabled=$false
 $rejected=$false; try { $null=New-OwnerDotnetPlan ($utf8.GetBytes((ConvertTo-Json -Depth 8 -InputObject $entry))) } catch { $rejected=$true }
 if (-not $rejected) { throw 'Disabled policy accepted.' }; $checked++
 Write-Output "DOTNET_PLAN_TESTS=PASS checked=$checked; private policy/Windows ACL/publication NOT_RUN."
 return
}
Assert-ZagentOwnerConsole
foreach ($p in @($InstallRoot,$DataRoot)) {
 if ($p -cnotmatch '\A[A-Za-z]:\\' -or -not (Test-Path -LiteralPath $p -PathType Container)) { throw 'Existing absolute directories required.' }
 Assert-ZagentPlainPath $p
}
$InstallRoot=(Resolve-Path -LiteralPath $InstallRoot).Path.TrimEnd('\')
$data=(Resolve-Path -LiteralPath $DataRoot).Path.TrimEnd('\')
Assert-ZagentOwnerAcl $data
Assert-ProfileAdminCoreStopped
Assert-ZagentPlainPath $dotnet
if (-not (Test-Path -LiteralPath $dotnet -PathType Leaf)) { throw 'Exact approved portable dotnet.exe missing.' }
$machinePath=Join-Path $data 'config\zagent.machine.json'
$machineBytes=Read-BoundedBytes $machinePath
$machine=(Read-StrictJson $machineBytes).Object
if ($machine.install_root.TrimEnd('\') -ine $InstallRoot -or $machine.data_root.TrimEnd('\') -ine $data) { throw 'Enrolled install/DataRoot mismatch.' }
$profilesPath=Join-Path $data 'files\config\profiles.json'
$profilesBytes=Read-BoundedBytes $profilesPath
$rows=(Read-StrictJson $profilesBytes).Object.profiles
$target=@($rows | Where-Object { $_.name -ceq 'agentRoot' })
if ($target.Count -ne 1 -or -not (Test-TrueFlag $target[0].enabled) -or -not (Test-TrueFlag $target[0].authorized_by_user) -or $target[0].mode -cne 'read-write' -or $target[0].root.TrimEnd('\') -cne 'D:\3-Ikbalzohr\Agent') { throw 'Existing approved agentRoot required.' }
$policyPath=Join-Path $data 'files\config\remote_execution_policy.json'
$before=Read-BoundedBytes $policyPath
$next=New-OwnerDotnetPlan $before
if ([Convert]::ToBase64String($before) -ceq [Convert]::ToBase64String($next)) { Write-Output 'DOTNET_ALREADY_APPROVED; no writes; Core NOT_STARTED.'; return }
$tag=[guid]::NewGuid().ToString('N')
$temp=$policyPath+'.'+$tag+'.tmp'; $backup=$policyPath+'.'+$tag+'.bak'
foreach ($p in @($temp,$backup)) { Assert-ZagentPlainPath $p; if (Test-Path -LiteralPath $p) { throw 'Private artifact collision.' } }
Assert-ProfileAdminCoreStopped
$stream=[IO.File]::Open($temp,[IO.FileMode]::CreateNew,[IO.FileAccess]::Write,[IO.FileShare]::None)
try { $stream.Write($next,0,$next.Length); $stream.Flush($true) } finally { $stream.Dispose() }
Set-ZagentOwnerAcl $temp
Assert-ProfileAdminCoreStopped
Assert-ZagentPlainPath $dotnet
if (-not (Test-Path -LiteralPath $dotnet -PathType Leaf)) { throw 'dotnet.exe disappeared; no replacement.' }
Assert-SnapshotUnchanged $machinePath $machineBytes
Assert-SnapshotUnchanged $profilesPath $profilesBytes
Assert-SnapshotUnchanged $policyPath $before
Assert-SnapshotUnchanged $temp $next
[IO.File]::Replace($temp,$policyPath,$backup)
Assert-SnapshotUnchanged $backup $before
Assert-SnapshotUnchanged $policyPath $next
Assert-ProfileAdminCoreStopped
Write-Output ('DOTNET_EXECUTABLE_APPROVED; executable='+$dotnet+'; exact backup/read-back verified; private backup='+$backup+'; existing executables/tools/limits/grants/OAuth unchanged; Core NOT_STARTED.')

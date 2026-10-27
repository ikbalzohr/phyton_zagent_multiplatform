# One explicit installed-package repair; never invoke through public MCP execution.
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
$oldExe='C:\Program Files\WindowsApps\Microsoft.PowerShell_7.6.8.0_x64__8wekyb3d8bbwe\pwsh.exe'
$newExe='C:\Program Files\WindowsApps\Microsoft.PowerShell_7.6.9.0_x64__8wekyb3d8bbwe\pwsh.exe'
function New-PowerShellExecutableRepair([byte[]]$Before) {
    $summary=@(Get-OwnerCommandPolicySummary $Before)
    $entries=@($summary | Where-Object { $_.profile_id -ceq 'agentRoot' })
    if ($entries.Count -ne 1 -or $entries[0].enabled -ne $true -or $entries[0].acknowledge_host_access -ne $true -or $entries[0].execution_mode -cne 'owner-account') { throw 'Exactly one existing approved agentRoot command policy required.' }
    $allowlist=$entries[0].allowed_executables
    if ($allowlist -isnot [array] -or @($allowlist | Where-Object { $_ -ceq $oldExe }).Count -ne 1 -or $newExe -cin $allowlist) { throw 'Exactly one old PowerShell entry and no new entry required; inspect uncertain state rather than retry.' }
    $parsed=Read-StrictJson $Before
    $oldToken=ConvertTo-Json -InputObject $oldExe -Compress
    $newToken=ConvertTo-Json -InputObject $newExe -Compress
    if ([regex]::Matches($parsed.Text,[regex]::Escape($oldToken)).Count -ne 1) { throw 'Ambiguous/noncanonical executable token; no write performed.' }
    $text=$parsed.Text.Replace($oldToken,$newToken)
    $next=$utf8.GetBytes($text)
    $null=Get-OwnerCommandPolicySummary $next
    if ([Convert]::ToBase64String($utf8.GetBytes($text.Replace($newToken,$oldToken))) -cne [Convert]::ToBase64String($Before)) { throw 'Unrelated bytes changed.' }
    return ,$next
}
if ($SelfTest) {
    $entry=[ordered]@{version=1;enabled=$true;execution_mode='owner-account';acknowledge_host_access=$true;profile_id='agentRoot';root='D:\3-Ikbalzohr\Agent';allowed_tools=@('files_command_capabilities','files_exec_command');allowed_executables=@('C:\Tools\git.exe',$oldExe);max_timeout_seconds=1800;max_output_chars=200000}
    $checked=0
    foreach ($version in @(1,2)) {
        $doc=$entry
        if ($version -eq 2) { $doc=@{version=2;profiles=@{agentRoot=$entry}} }
        $before=$utf8.GetBytes((ConvertTo-Json -Depth 10 -InputObject $doc))
        $next=New-PowerShellExecutableRepair $before
        $original=(Read-StrictJson $before).Text
        $expected=$original.Replace((ConvertTo-Json -InputObject $oldExe -Compress),(ConvertTo-Json -InputObject $newExe -Compress))
        if ($utf8.GetString($next) -cne $expected) { throw 'Unexpected candidate bytes.' }; $checked++
        $rejected=$false; try { $null=New-PowerShellExecutableRepair $next } catch { $rejected=$true }
        if (-not $rejected) { throw 'Repeated apply must fail closed.' }; $checked++
    }
    $entry.profile_id='other'
    $rejected=$false; try { $null=New-PowerShellExecutableRepair ($utf8.GetBytes((ConvertTo-Json -Depth 10 -InputObject $entry))) } catch { $rejected=$true }
    if (-not $rejected) { throw 'Wrong profile accepted.' }; $checked++
    Write-Output "PURE_REPAIR_TESTS=PASS checked=$checked; Windows ACL/publication NOT_RUN."
    return
}
Assert-ZagentOwnerConsole
foreach ($path in @($InstallRoot,$DataRoot)) {
    if ($path -cnotmatch '\A[A-Za-z]:\\' -or -not (Test-Path -LiteralPath $path -PathType Container)) { throw 'Existing absolute owner-local directory required.' }
    Assert-ZagentPlainPath $path
}
$InstallRoot=(Resolve-Path -LiteralPath $InstallRoot).Path.TrimEnd('\')
$data=(Resolve-Path -LiteralPath $DataRoot).Path.TrimEnd('\')
Assert-ZagentOwnerAcl $data
Assert-ProfileAdminCoreStopped
Assert-ZagentPlainPath $newExe
if (-not (Test-Path -LiteralPath $newExe -PathType Leaf)) { throw 'Replacement executable unavailable.' }
if (Test-Path -LiteralPath $oldExe) { throw 'Old executable exists; this missing-package repair does not apply.' }
$machinePath=Join-Path $data 'config\zagent.machine.json'
$machineBytes=Read-BoundedBytes $machinePath
$machine=(Read-StrictJson $machineBytes).Object
if ($machine.install_root.TrimEnd('\') -ine $InstallRoot -or $machine.data_root.TrimEnd('\') -ine $data) { throw 'Enrolled install/DataRoot mismatch.' }
$policyPath=Join-Path $data 'files\config\remote_execution_policy.json'
$before=Read-BoundedBytes $policyPath
$next=New-PowerShellExecutableRepair $before
$tag=[guid]::NewGuid().ToString('N')
$temp=$policyPath+'.'+$tag+'.tmp'; $backup=$policyPath+'.'+$tag+'.bak'
foreach ($path in @($temp,$backup)) {
    Assert-ZagentPlainPath $path
    if (Test-Path -LiteralPath $path) { throw 'Private artifact collision.' }
}
Assert-ProfileAdminCoreStopped
$stream=[IO.File]::Open($temp,[IO.FileMode]::CreateNew,[IO.FileAccess]::Write,[IO.FileShare]::None)
try { $stream.Write($next,0,$next.Length); $stream.Flush($true) } finally { $stream.Dispose() }
Set-ZagentOwnerAcl $temp
Assert-ProfileAdminCoreStopped
Assert-ZagentPlainPath $newExe
if (-not (Test-Path -LiteralPath $newExe -PathType Leaf) -or (Test-Path -LiteralPath $oldExe)) { throw 'Executable placement changed; no replacement performed.' }
Assert-SnapshotUnchanged $machinePath $machineBytes
Assert-SnapshotUnchanged $policyPath $before
Assert-SnapshotUnchanged $temp $next
[IO.File]::Replace($temp,$policyPath,$backup)
Assert-SnapshotUnchanged $backup $before
Assert-SnapshotUnchanged $policyPath $next
Assert-ProfileAdminCoreStopped
Write-Output ('POWERSHELL_POLICY_PATH_REPAIRED; exact backup/read-back verified; private backup='+$backup+'; only existing agentRoot PowerShell path 7.6.8.0->7.6.9.0 changed; other executables/tools/limits/OAuth unchanged; Core NOT_STARTED.')

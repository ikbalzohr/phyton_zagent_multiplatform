# Rebind exactly ONE existing owner Files grant to an already-approved profile.
# Noninteractive by design: no consent prompt, no per-operation approval, no OAuth action.
# Touches ONLY files_resource.profile_id and files_resource.allowed_profile_ids.
# expires_at, revocation, scopes, tools, tool_policy, resource placement and every
# unrelated configuration byte are preserved and proven byte-for-byte below.
[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][string]$InstallRoot,
    [Parameter(Mandatory=$true)][string]$DataRoot,
    [Parameter(Mandatory=$true)][string]$NewProfileId,
    [Parameter(Mandatory=$true)][string[]]$AllowedProfileIds
)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
. (Join-Path $PSScriptRoot 'WindowsDashboard-Provisioning.ps1')
. (Join-Path $PSScriptRoot 'Owner-PrivateConfig.ps1')
. (Join-Path $PSScriptRoot 'ProfileAdministrationBootstrap.ps1')
Assert-ZagentOwnerConsole
$InstallRoot = (Resolve-Path -LiteralPath $InstallRoot).Path
# Lower-case $data is required by Assert-MigrationPrivatePath in Owner-PrivateConfig.ps1.
$data = (Resolve-Path -LiteralPath $DataRoot).Path
Assert-ZagentPlainPath $InstallRoot
Assert-ZagentOwnerAcl $data
$idPattern = '\A[A-Za-z0-9_-]{1,256}\z'
if ($NewProfileId -cnotmatch $idPattern) { throw 'Explicit bounded profile identifier required; no trim or repair.' }
$currentAllow = @($AllowedProfileIds)
if ($currentAllow.Count -lt 1 -or $currentAllow.Count -gt 128) { throw 'Nonempty bounded allowed profile list required.' }
$seen = [Collections.Generic.HashSet[string]]::new([StringComparer]::Ordinal)
foreach ($id in $currentAllow) {
    if ($id -isnot [string] -or $id -cnotmatch $idPattern -or -not $seen.Add($id)) { throw 'Invalid/duplicate allowed profile identifier.' }
}
if ($NewProfileId -cnotin $currentAllow) { throw 'Default profile must be a member of the allowed list.' }
Assert-CoreStopped
$path = Join-Path $data 'tunnel\config\tunnel.json'
$before = Read-BoundedBytes $path
$parsed = Read-StrictJson $before
$rs = $parsed.Object.resource_server
if ($rs.issuer -cne 'https://vmi3669591.contaboserver.net/realms/zagent' -or
    $rs.resource_uri -cne 'https://zagent.ikbalzohr.web.id/mcp') { throw 'Unexpected issuer/resource; no write performed.' }
$entries = @($rs.grants.PSObject.Properties)
if ($entries.Count -ne 1) { throw 'Exactly one existing owner grant required; no write performed.' }
$principal = 'principal_v1_41d40891edc920d08c8bf7d58f508bb1a082a9dc8dc5bb70f4fa2d913161a59d'
if ($entries[0].Name -cne $principal) { throw 'Unexpected owner principal; no write performed.' }
$grant = $entries[0].Value
$resource = $grant.files_resource
$now = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds()
if ($grant.revoked -isnot [bool] -or $grant.revoked -ne $false) { throw 'Revoked grants are not rebound by this helper; authorize first.' }
if (($grant.expires_at -isnot [long] -and $grant.expires_at -isnot [int]) -or $grant.expires_at -le $now) { throw 'Existing finite unexpired grant required; run Renew-OwnerFilesGrant.ps1 first.' }
if ($resource -isnot [pscustomobject] -or
    $resource.revoked -isnot [bool] -or $resource.revoked -ne $false -or
    $resource.kind -isnot [string] -or $resource.kind -cne 'files' -or
    $resource.resource_id -isnot [string] -or [string]::IsNullOrWhiteSpace($resource.resource_id) -or $resource.resource_id.Length -gt 256 -or
    $resource.device_id -isnot [string] -or [string]::IsNullOrWhiteSpace($resource.device_id) -or
    $resource.installation_id -isnot [string] -or [string]::IsNullOrWhiteSpace($resource.installation_id)) { throw 'Existing active files resource placement required.' }
if ($resource.profile_id -isnot [string] -or $resource.profile_id -cnotmatch $idPattern) { throw 'Existing default profile identifier required.' }
if ($grant.scopes -isnot [array] -or 'files:read' -cnotin $grant.scopes) { throw 'Existing files:read grant scope required; no expansion.' }
if ($grant.tools -isnot [array] -or $grant.tools.Count -lt 1 -or $grant.tools.Count -gt 512) { throw 'Existing bounded grant tool list required.' }
$oldProfile = $resource.profile_id
$allowProperty = $resource.PSObject.Properties['allowed_profile_ids']
$oldAllow = @($oldProfile)
if ($null -ne $allowProperty) {
    if ($allowProperty.Value -isnot [array] -or $allowProperty.Value.Count -lt 1 -or $allowProperty.Value.Count -gt 128) { throw 'Malformed existing profile allowlist.' }
    $oldAllow = @($allowProperty.Value)
    $seenOld = [Collections.Generic.HashSet[string]]::new([StringComparer]::Ordinal)
    foreach ($id in $oldAllow) {
        if ($id -isnot [string] -or $id -cnotmatch $idPattern -or -not $seenOld.Add($id)) { throw 'Invalid/duplicate existing allowed profile identifier.' }
    }
    if ($oldProfile -cnotin $oldAllow) { throw 'Existing default is not in its own allowlist.' }
}
if ($oldProfile -ceq $NewProfileId -and ((@($oldAllow) -join ',') -ceq (@($currentAllow) -join ','))) {
    Assert-CoreStopped
    Assert-SnapshotUnchanged $path $before
    Write-Output ('PROFILE_GRANT_ALREADY_CURRENT; profile_id=' + $NewProfileId + '; no writes; Core not started.')
    return
}
$resPath = @('resource_server','grants',$principal,'files_resource')
$profileToken = ConvertTo-Json -InputObject $NewProfileId -Compress
$allowToken = ConvertTo-Json -InputObject @($currentAllow) -Compress
# Replace ONE existing token at a time. Original token text is captured first so the
# reverse edit reproduces the original bytes even when the source formatting differs.
$spanProfile = Get-ProfileAdminSpan $parsed.Text ($resPath + @('profile_id'))
$oldProfileToken = $parsed.Text.Substring($spanProfile.Start, $spanProfile.Length)
$text1 = $parsed.Text.Remove($spanProfile.Start, $spanProfile.Length).Insert($spanProfile.Start, $profileToken)
$inserted = $null
$insertAt = -1
if ($null -ne $allowProperty) {
    $spanAllow = Get-ProfileAdminSpan $text1 ($resPath + @('allowed_profile_ids'))
    $oldAllowToken = $text1.Substring($spanAllow.Start, $spanAllow.Length)
    $text2 = $text1.Remove($spanAllow.Start, $spanAllow.Length).Insert($spanAllow.Start, $allowToken)
} else {
    # No existing allowlist: insert one member immediately inside the resource object.
    $spanParent = Get-ProfileAdminSpan $text1 $resPath
    $insertAt = $spanParent.Start + $spanParent.Length - 1
    $inserted = ',"allowed_profile_ids":' + $allowToken
    $text2 = $text1.Insert($insertAt, $inserted)
}
$next = $utf8.GetBytes($text2)
$check = (Read-StrictJson $next).Object.resource_server.grants.$principal.files_resource
if ($check.profile_id -cne $NewProfileId) { throw 'Rebind validation failed; no write performed.' }
if ((@($check.allowed_profile_ids) -join ',') -cne (@($currentAllow) -join ',')) { throw 'Rebind allowlist validation failed; no write performed.' }
# Reverse BOTH edits in reverse order; the original bytes must be reproduced exactly.
$reverse = $text2
if ($null -eq $inserted) {
    $spanAllowBack = Get-ProfileAdminSpan $reverse ($resPath + @('allowed_profile_ids'))
    $reverse = $reverse.Remove($spanAllowBack.Start, $spanAllowBack.Length).Insert($spanAllowBack.Start, $oldAllowToken)
} else {
    $reverse = $reverse.Remove($insertAt, $inserted.Length)
}
$spanProfileBack = Get-ProfileAdminSpan $reverse ($resPath + @('profile_id'))
$reverse = $reverse.Remove($spanProfileBack.Start, $spanProfileBack.Length).Insert($spanProfileBack.Start, $oldProfileToken)
if ([Convert]::ToBase64String($utf8.GetBytes($reverse)) -cne [Convert]::ToBase64String($before)) { throw 'Unrelated configuration bytes changed; no write performed.' }
$tag = [guid]::NewGuid().ToString('N')
$temp = $path + '.' + $tag + '.tmp'
$backup = $path + '.' + $tag + '.bak'
Assert-ZagentPlainPath $temp
Assert-ZagentPlainPath $backup
if ((Test-Path -LiteralPath $temp) -or (Test-Path -LiteralPath $backup)) { throw 'Private artifact collision.' }
$stream = [IO.File]::Open($temp, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write, [IO.FileShare]::None)
try { $stream.Write($next, 0, $next.Length); $stream.Flush($true) } finally { $stream.Dispose() }
Set-ZagentOwnerAcl $temp
Assert-CoreStopped
Assert-SnapshotUnchanged $path $before
[IO.File]::Replace($temp, $path, $backup)
Assert-MigrationPrivatePath $backup
if ([Convert]::ToBase64String((Read-BoundedBytes $backup)) -cne [Convert]::ToBase64String($before)) { throw 'Backup mismatch; keep Core stopped.' }
if ([Convert]::ToBase64String((Read-BoundedBytes $path)) -cne [Convert]::ToBase64String($next)) { throw 'Read-back mismatch; keep Core stopped.' }
Assert-CoreStopped
Write-Output ('Private backup: ' + $backup)
Write-Output ('PROFILE_GRANT_REBOUND; profile_id=' + $NewProfileId + '; allowed_profile_ids=' + ($currentAllow -join ',') + '; previous_profile_id=' + $oldProfile)
Write-Output 'Only files_resource.profile_id/allowed_profile_ids changed; expires_at, revocation, scopes, tools, tool_policy and OAuth preserved. Exact read-back verified; Core NOT_STARTED.'

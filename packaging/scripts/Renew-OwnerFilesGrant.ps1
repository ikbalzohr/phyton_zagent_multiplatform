# Renew exactly one existing, unrevoked Files grant; no token/profile/policy changes.
[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][string]$InstallRoot,
    [Parameter(Mandatory=$true)][string]$DataRoot,
    [ValidateSet(7, 30)][int]$Days = 30
)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
. (Join-Path $PSScriptRoot 'WindowsDashboard-Provisioning.ps1')
. (Join-Path $PSScriptRoot 'Owner-PrivateConfig.ps1')
Assert-ZagentOwnerConsole
$InstallRoot = (Resolve-Path -LiteralPath $InstallRoot).Path
$data = (Resolve-Path -LiteralPath $DataRoot).Path
Assert-ZagentPlainPath $InstallRoot
Assert-ZagentOwnerAcl $data
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
if ($grant.revoked -cne $false) { throw 'Revoked grants cannot be renewed by this helper.' }
if (($grant.expires_at -isnot [long] -and $grant.expires_at -isnot [int]) -or $grant.expires_at -le 0) { throw 'Existing finite integer grant expiry required.' }
$oldExpiry = [long]$grant.expires_at
$newExpiry = [DateTimeOffset]::UtcNow.AddDays($Days).ToUnixTimeSeconds()
if ($newExpiry -le $oldExpiry) { throw 'Refusing to shorten an existing grant.' }
# Unique numeric token replacement preserves EVERY other original character.
$pattern = '("expires_at"\s*:\s*)' + $oldExpiry.ToString([Globalization.CultureInfo]::InvariantCulture) + '(?=\s*[,}])'
$matches = [regex]::Matches($parsed.Text, $pattern)
if ($matches.Count -ne 1) { throw 'Ambiguous expiry token; no write performed.' }
$match = $matches[0]
$prefixLength = $match.Groups[1].Length
$start = $match.Index + $prefixLength
$oldLength = $match.Length - $prefixLength
$nextText = $parsed.Text.Remove($start, $oldLength).Insert($start, $newExpiry.ToString([Globalization.CultureInfo]::InvariantCulture))
$next = $utf8.GetBytes($nextText)
$check = (Read-StrictJson $next).Object.resource_server
if ($check.grants.$principal.expires_at -ne $newExpiry -or $check.grants.$principal.revoked -cne $false) { throw 'Expiry-only validation failed.' }
# Reversing the single edit must reproduce every original byte, including BOM.
$roundtrip = $nextText.Remove($start, $newExpiry.ToString([Globalization.CultureInfo]::InvariantCulture).Length).Insert($start, $oldExpiry.ToString([Globalization.CultureInfo]::InvariantCulture))
if ([Convert]::ToBase64String($utf8.GetBytes($roundtrip)) -cne [Convert]::ToBase64String($before)) { throw 'Unrelated configuration bytes changed.' }
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
Write-Host ('Private backup: ' + $backup)
Write-Host ('GRANT_RENEWED; expires_at=' + $newExpiry + '; expires_local=' + [DateTimeOffset]::FromUnixTimeSeconds($newExpiry).ToLocalTime().ToString('o'))
Write-Host 'Only existing expires_at changed; revocation/tools/scopes/root/policy and OAuth tokens preserved. Backup and exact read-back verified.'

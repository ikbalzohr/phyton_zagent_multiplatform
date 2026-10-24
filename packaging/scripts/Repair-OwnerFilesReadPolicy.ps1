[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][string]$InstallRoot
)
# Offline, owner-only repair of two Files read-tool policies. No grant activation/renewal/network.
# Windows PowerShell 5.1+. Source-only review is not parser/runtime acceptance.
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'WindowsDashboard-Provisioning.ps1')
Assert-ZagentOwnerConsole
$oldUri = 'https://vmi3669591.contaboserver.net/mcp'
$newUri = 'https://zagent.ikbalzohr.web.id/mcp'
$issuer = 'https://vmi3669591.contaboserver.net/realms/zagent'
$utf8 = [Text.UTF8Encoding]::new($false, $true)

function Assert-MigrationPrivatePath([string]$Path) {
    # Core-generated configs may inherit owner-only rights. Validate every ancestor
    # back to the protected DataRoot rather than requiring protected ACLs on each leaf.
    Assert-ZagentPlainPath $Path
    $full = [IO.Path]::GetFullPath($Path)
    $anchor = [IO.Path]::GetFullPath($data).TrimEnd('\')
    if ($full -ine $anchor -and -not $full.StartsWith(($anchor + '\'), [StringComparison]::OrdinalIgnoreCase)) { throw 'Private path outside the reviewed DataRoot.' }
    $owner = [Security.Principal.WindowsIdentity]::GetCurrent().User
    $walk = $full
    while ($true) {
        $acl = Get-Acl -LiteralPath $walk
        $rules = @($acl.GetAccessRules($true,$true,[Security.Principal.SecurityIdentifier]))
        if ($acl.GetOwner([Security.Principal.SecurityIdentifier]).Value -cne $owner.Value -or
            $rules.Count -ne 1 -or $rules[0].IdentityReference.Value -cne $owner.Value -or
            $rules[0].AccessControlType -ne [Security.AccessControl.AccessControlType]::Allow -or
            $rules[0].FileSystemRights -ne [Security.AccessControl.FileSystemRights]::FullControl -or
            $rules[0].PropagationFlags -ne [Security.AccessControl.PropagationFlags]::None) { throw 'Private path requires owner-only FullControl, including its parent directories.' }
        $isDirectory = (Get-Item -LiteralPath $walk -Force).PSIsContainer
        $expected = [Security.AccessControl.InheritanceFlags]::None
        if ($isDirectory) { $expected = [Security.AccessControl.InheritanceFlags]::ContainerInherit -bor [Security.AccessControl.InheritanceFlags]::ObjectInherit }
        if ($rules[0].InheritanceFlags -ne $expected) { throw 'Private path inheritance flags mismatch.' }
        if ($walk -ieq $anchor) { Assert-ZagentOwnerAcl $anchor; break }
        $walk = [IO.Path]::GetDirectoryName($walk)
        if (-not $walk) { throw 'Private DataRoot ancestor missing.' }
    }
}

function Read-BoundedBytes([string]$Path) {
    Assert-ZagentPlainPath $Path
    Assert-MigrationPrivatePath $Path
    # Check length before allocation, then bound the read even if the file grows.
    $stream = [IO.File]::Open($Path, [IO.FileMode]::Open, [IO.FileAccess]::Read, [IO.FileShare]::Read)
    try {
        if ($stream.Length -lt 2 -or $stream.Length -gt 1048576) { throw 'Private JSON size outside 2..1048576 bytes.' }
        $buffer = New-Object byte[] ([int]$stream.Length)
        $offset = 0
        while ($offset -lt $buffer.Length) {
            $n = $stream.Read($buffer, $offset, $buffer.Length - $offset)
            if ($n -eq 0) { throw 'Private JSON changed during read.' }
            $offset += $n
        }
        if ($stream.ReadByte() -ne -1) { throw 'Private JSON grew during read.' }
        return ,$buffer
    } finally { $stream.Dispose() }
}

function Read-StrictJson([byte[]]$Bytes) {
    # Validate grammar/depth and reject duplicate names BEFORE ConvertFrom-Json can
    # collapse them. OrdinalIgnoreCase also rejects PowerShell property collisions.
    # Keep original character spans: only the two approved string tokens are edited.
    $s = @{ Text = $utf8.GetString($Bytes); Index = 0; Nodes = 0; Clock = [Diagnostics.Stopwatch]::StartNew(); ResourceUri = $null; PolicyRevision = $null; ToolPolicy = $null; RootEnd = $null }
    if ($s.Text.Length -gt 0 -and $s.Text[0] -eq [char]0xFEFF) { $s.Index = 1 }
    function Skip-JsonSpace {
        while ($s.Index -lt $s.Text.Length -and " `t`r`n".IndexOf($s.Text[$s.Index]) -ge 0) { $s.Index++ }
    }
    function Read-JsonString {
        $m = [regex]::Match($s.Text.Substring($s.Index), '\A"(?:[^"\\\x00-\x1f]|\\(?:["\\/bfnrt]|u[0-9a-fA-F]{4}))*"', [Text.RegularExpressions.RegexOptions]::None, [TimeSpan]::FromSeconds(2))
        if (-not $m.Success) { throw 'Invalid JSON string.' }
        $s.Index += $m.Length
        try { $decoded = @(ConvertFrom-Json -InputObject ('[' + $m.Value + ']')) }
        catch { throw 'Private JSON string conversion failed.' }
        return [string]$decoded[0]
    }
    function Read-JsonValue([int]$depth, [string[]]$path) {
        if ($depth -gt 64) { throw 'JSON nesting exceeds 64.' }
        $s.Nodes++
        if ($s.Nodes -gt 32768 -or $s.Clock.Elapsed.TotalSeconds -gt 15) { throw 'Private JSON parse budget exceeded.' }
        Skip-JsonSpace
        if ($s.Index -ge $s.Text.Length) { throw 'Incomplete JSON.' }
        $start = $s.Index
        $ch = $s.Text[$s.Index]
        if ($ch -eq '{') {
            $s.Index++; Skip-JsonSpace
            $keys = [Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase)
            if ($s.Index -lt $s.Text.Length -and $s.Text[$s.Index] -eq '}') {
                $s.Index++
                if ($path.Count -eq 1 -and $path[0] -ceq 'tool_policy') { $s.ToolPolicy = @{ Start = $start; Length = ($s.Index - $start) } }
                return
            }
            while ($true) {
                Skip-JsonSpace
                $key = Read-JsonString
                if (-not $keys.Add($key)) { throw 'Duplicate JSON member rejected.' }
                Skip-JsonSpace
                if ($s.Index -ge $s.Text.Length -or $s.Text[$s.Index] -ne ':') { throw 'JSON colon required.' }
                $s.Index++
                Read-JsonValue ($depth + 1) (@($path) + @($key))
                Skip-JsonSpace
                if ($s.Index -ge $s.Text.Length) { throw 'Incomplete JSON object.' }
                $separator = $s.Text[$s.Index]; $s.Index++
                if ($separator -eq '}') { break }
                if ($separator -ne ',') { throw 'JSON object separator required.' }
            }
        } elseif ($ch -eq '[') {
            $s.Index++; Skip-JsonSpace
            if ($s.Index -lt $s.Text.Length -and $s.Text[$s.Index] -eq ']') { $s.Index++; return }
            while ($true) {
                Read-JsonValue ($depth + 1) (@($path) + @('[]'))
                Skip-JsonSpace
                if ($s.Index -ge $s.Text.Length) { throw 'Incomplete JSON array.' }
                $separator = $s.Text[$s.Index]; $s.Index++
                if ($separator -eq ']') { break }
                if ($separator -ne ',') { throw 'JSON array separator required.' }
            }
        } elseif ($ch -eq '"') {
            $null = Read-JsonString
            if ($path.Count -eq 2 -and $path[0] -ceq 'resource_server') {
                $span = @{ Start = $start; Length = ($s.Index - $start) }
                if ($path[1] -ceq 'resource_uri') { $s.ResourceUri = $span }
                if ($path[1] -ceq 'policy_revision') { $s.PolicyRevision = $span }
            }
        } else {
            $m = [regex]::Match($s.Text.Substring($s.Index), '\A(?:true|false|null|-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?)')
            if (-not $m.Success) { throw 'Invalid JSON value.' }
            $s.Index += $m.Length
        }
        if ($path.Count -eq 1 -and $path[0] -ceq 'tool_policy') { $s.ToolPolicy = @{ Start = $start; Length = ($s.Index - $start) } }
        if ($depth -eq 0) { $s.RootEnd = $s.Index - 1 }
    }
    Skip-JsonSpace
    if ($s.Index -ge $s.Text.Length -or $s.Text[$s.Index] -ne '{') { throw 'JSON object required.' }
    Read-JsonValue 0 @()
    Skip-JsonSpace
    if ($s.Index -ne $s.Text.Length) { throw 'Trailing JSON data rejected.' }
    try { $object = ConvertFrom-Json -InputObject ($s.Text.TrimStart([char]0xFEFF)) }
    catch { throw 'Private JSON object conversion failed.' }
    return @{ Object = $object; Text = $s.Text; ResourceUri = $s.ResourceUri; PolicyRevision = $s.PolicyRevision; ToolPolicy = $s.ToolPolicy; RootEnd = $s.RootEnd }
}

function Assert-SnapshotUnchanged([string]$Path, [byte[]]$Before) {
    $now = Read-BoundedBytes $Path
    if ([Convert]::ToBase64String($now) -cne [Convert]::ToBase64String($Before)) { throw 'Concurrent configuration change; no replacement performed.' }
}
function Find-Core {
    # Query errors fail closed. Reject inaccessible executable metadata, not just no matches.
    $all = @(Get-CimInstance Win32_Process -Filter "Name='Zagent.Core.exe'")
    foreach ($p in $all) { if (-not $p.ExecutablePath) { throw 'Core executable metadata unavailable.' } }
    return @($all | Where-Object { $_.ExecutablePath.StartsWith(($InstallRoot + '\'), [StringComparison]::OrdinalIgnoreCase) })
}
function Assert-CoreStopped {
    if (@(Find-Core).Count -ne 0) { throw 'Core is still running; no write performed.' }
}
function Read-OneArgument([string]$CommandLine, [string]$Name) {
    $occurrences = [regex]::Matches($CommandLine, ('(?:^|\s)' + [regex]::Escape($Name) + '(?=\s|=|$)'))
    $matches = [regex]::Matches($CommandLine, ('(?:^|\s)' + [regex]::Escape($Name) + '\s+(?:"([^"]+)"|(\S+))'))
    if ($occurrences.Count -ne 1 -or $matches.Count -ne 1) { throw 'One unambiguous Core path argument required.' }
    $value = $matches[0].Groups[1].Value
    if (-not $value) { $value = $matches[0].Groups[2].Value }
    if ($value -notmatch '\A[A-Za-z]:\\') { throw 'Fully qualified local-drive Core path required; no drive-relative or UNC path.' }
    return (Resolve-Path -LiteralPath $value).Path
}

$InstallRoot = (Resolve-Path -LiteralPath $InstallRoot).Path.TrimEnd('\')
if ($InstallRoot -notmatch '\A[A-Za-z]:\\') { throw 'Local-drive installation root required.' }
Assert-ZagentPlainPath $InstallRoot

$processes = @(Find-Core)
if ($processes.Count -ne 1) { throw 'Exactly one running Core for this installation is required to discover DataRoot; do not start another enrollment.' }
$coreExe = (Resolve-Path -LiteralPath $processes[0].ExecutablePath).Path
Assert-ZagentPlainPath $coreExe
if (-not (Test-Path -LiteralPath $coreExe -PathType Leaf) -or -not $coreExe.StartsWith(($InstallRoot + '\'), [StringComparison]::OrdinalIgnoreCase)) { throw 'Existing Core executable outside installation.' }
$commandLine = $processes[0].CommandLine
if (-not $commandLine) { throw 'Core command line unavailable.' }
if ((Read-OneArgument $commandLine '--root').TrimEnd('\') -ine $InstallRoot) { throw 'Core installation root mismatch.' }
$data = Read-OneArgument $commandLine '--data-root'
Assert-ZagentPlainPath $data
Assert-ZagentOwnerAcl $data
$configDir = Join-Path $data 'tunnel\config'
# Existing private directories only; never repair/adopt an ambiguous ACL.
foreach ($dir in @((Join-Path $data 'config'), (Join-Path $data 'files\config'), $configDir)) {
    if (-not (Test-Path -LiteralPath $dir -PathType Container)) { throw 'Existing private configuration directory missing.' }
    Assert-MigrationPrivatePath $dir
}
$dashboardPath = Join-Path $data 'config\dashboard.json'
$identityPath = Join-Path $data 'config\device_identity.json'
$profilesPath = Join-Path $data 'files\config\profiles.json'
$credentialPath = Join-Path $data 'config\oauth-introspection.dpapi.json'
Assert-ZagentOwnerAcl $credentialPath
$target = Join-Path $configDir 'tunnel.json'
$snapshots = @{}
foreach ($path in @($dashboardPath, $identityPath, $profilesPath, $credentialPath)) { $snapshots[$path] = Read-BoundedBytes $path }

function Assert-ReviewedMetadata {
    foreach ($path in @($dashboardPath, $identityPath, $profilesPath, $credentialPath)) { Assert-SnapshotUnchanged $path $snapshots[$path] }
    $dashboard = (Read-StrictJson $snapshots[$dashboardPath]).Object
    $identity = (Read-StrictJson $snapshots[$identityPath]).Object
    $profiles = (Read-StrictJson $snapshots[$profilesPath]).Object
    $credential = (Read-StrictJson $snapshots[$credentialPath]).Object
    if ($dashboard.WorkspaceId -cne 'workspace-local' -or $identity.device_id -cne '7338141d-ab55-4d78-a97e-35336f970fb5' -or $identity.installation_id -cne '7c82db6b-f6f2-4072-bd38-7ed763aa45d3') { throw 'Reviewed owner installation metadata changed.' }
    $approved = @($profiles.profiles | Where-Object { $_.name -ceq 'appBridge' })
    $expectedRoot = Join-Path $InstallRoot 'workspace'
    if ($profiles.active_profile -cne 'appBridge' -or $approved.Count -ne 1 -or $approved[0].enabled -isnot [bool] -or $approved[0].enabled -ne $true -or $approved[0].mode -cne 'read-only' -or -not [IO.Path]::IsPathRooted($approved[0].root) -or [IO.Path]::GetFullPath($approved[0].root).TrimEnd('\') -ine $expectedRoot.TrimEnd('\')) { throw 'Reviewed read-only Files approval changed.' }
    Assert-ZagentPlainPath $expectedRoot
    if (-not (Test-Path -LiteralPath $expectedRoot -PathType Container)) { throw 'Approved workspace root missing.' }
    # Inspect only the trusted DPAPI envelope metadata; never decrypt or log ciphertext.
    if (@($credential.PSObject.Properties).Count -ne 3 -or $credential.version -ne 1 -or $credential.scope -cne 'CurrentUser' -or $credential.protected_payload -isnot [string] -or $credential.protected_payload.Length -eq 0 -or $credential.protected_payload -notmatch '\A[A-Za-z0-9+/]+={0,2}\z' -or ($credential.protected_payload.Length % 4) -ne 0) { throw 'Existing DPAPI store metadata invalid; no enrollment or decryption performed.' }
}
Assert-ReviewedMetadata
$before = Read-BoundedBytes $target
$parsed = Read-StrictJson $before
$resource = $parsed.Object.resource_server
if ($resource.issuer -cne $issuer -or $resource.introspection_endpoint -cne ($issuer + '/protocol/openid-connect/token/introspect') -or $resource.introspection_client_id -cne 'zagent-resource-server' -or $resource.introspection_secret_env -cne 'ZAGENT_OAUTH_INTROSPECTION_SECRET' -or $resource.workspace_id -cne 'workspace-local' -or @($resource.authorization_servers).Count -ne 1 -or $resource.authorization_servers[0] -cne $issuer -or $resource.grants -isnot [pscustomobject] -or $null -eq $parsed.ResourceUri -or $null -eq $parsed.PolicyRevision -or [string]::IsNullOrWhiteSpace($resource.policy_revision)) { throw 'Existing resource policy does not match the trusted owner contract.' }
if ($resource.resource_uri -cne $newUri) { throw 'Expected current Cloudflare resource URI; no write performed.' }
# Require the already-approved narrow grant; never activate or extend it here.
$principal = 'principal_v1_41d40891edc920d08c8bf7d58f508bb1a082a9dc8dc5bb70f4fa2d913161a59d'
$grantProperty = $resource.grants.PSObject.Properties[$principal]
if ($null -eq $grantProperty) { throw 'Reviewed existing grant missing.' }
$grant = $grantProperty.Value
if ($grant.revoked -isnot [bool] -or $grant.revoked -ne $false -or
    (@($grant.scopes) -join ',') -cne 'files:read' -or
    (@($grant.tools) -join ',') -cne 'files_stat,files_read' -or
    $grant.files_resource.revoked -isnot [bool] -or $grant.files_resource.revoked -ne $false -or
    $grant.files_resource.profile_id -cne 'appBridge' -or
    $grant.files_resource.resource_id -cne 'workspace:workspace-local:approved-repository' -or
    $grant.files_resource.kind -cne 'files' -or
    $grant.files_resource.device_id -cne '7338141d-ab55-4d78-a97e-35336f970fb5' -or
    $grant.files_resource.installation_id -cne '7c82db6b-f6f2-4072-bd38-7ed763aa45d3' -or
    $grant.expires_at -le [DateTimeOffset]::UtcNow.ToUnixTimeSeconds()) { throw 'Grant differs from the active reviewed read-only approval or has expired; no renewal performed.' }
$policyProperty = $parsed.Object.PSObject.Properties['tool_policy']
$policy = [pscustomobject]@{}
if ($null -ne $policyProperty) {
    if ($policyProperty.Value -isnot [pscustomobject] -or $null -eq $parsed.ToolPolicy) { throw 'tool_policy must be an object.' }
    $policy = $policyProperty.Value
}
$changed = $false
foreach ($name in @('files_stat','files_read')) {
    $entry = $policy.PSObject.Properties[$name]
    if ($null -ne $entry) {
        if ($entry.Value -isnot [pscustomobject] -or $entry.Value.scope -cne 'files:read') { throw 'Conflicting Files tool policy; no overwrite performed.' }
        $enabled = $entry.Value.PSObject.Properties['enabled']
        if ($null -ne $enabled -and ($enabled.Value -isnot [bool] -or $enabled.Value -ne $true)) { throw 'Conflicting Files tool policy: explicitly disabled; no overwrite performed.' }
    } else {
        $policy | Add-Member -NotePropertyName $name -NotePropertyValue ([pscustomobject]@{ scope = 'files:read' })
        $changed = $true
    }
}
if (-not $changed) {
    Assert-ReviewedMetadata
    Assert-SnapshotUnchanged $target $before
    Write-Host 'FILES_READ_POLICY_ALREADY_CURRENT; no write or grant change; authenticated Files call NOT_VERIFIED.'
    return
}
Write-Host 'Use Overview > Stop Core now (NOT Stop all agents). Keep Core stopped until this helper finishes.'
$null = Read-Host 'Press ENTER only after Core has exited'
Assert-CoreStopped
Assert-ReviewedMetadata
Assert-SnapshotUnchanged $target $before
if ($grant.expires_at -le [DateTimeOffset]::UtcNow.ToUnixTimeSeconds()) { throw 'Grant expired while waiting; no renewal performed.' }
# Edit only the tool-policy token (or insert a missing root member) and revision.
# All resource grants, bindings, expiry and other configuration bytes are untouched.
$revision = 'files-read-policy-' + [guid]::NewGuid().ToString('N')
$policyJson = ConvertTo-Json -InputObject $policy -Depth 64 -Compress
$policyEdit = @{ Start = $parsed.RootEnd; Length = 0; Value = ',"tool_policy":' + $policyJson }
if ($null -ne $parsed.ToolPolicy) { $policyEdit = @{ Start = $parsed.ToolPolicy.Start; Length = $parsed.ToolPolicy.Length; Value = $policyJson } }
$revisionEdit = @{ Start = $parsed.PolicyRevision.Start; Length = $parsed.PolicyRevision.Length; Value = '"' + $revision + '"' }
$next = $parsed.Text
foreach ($edit in @(@($policyEdit, $revisionEdit) | Sort-Object -Property Start -Descending)) {
    $next = $next.Remove($edit.Start, $edit.Length).Insert($edit.Start, $edit.Value)
}
$bytes = $utf8.GetBytes($next)
if ($bytes.Length -gt 1048576) { throw 'Repaired JSON exceeds size bound.' }
$verified = Read-StrictJson $bytes
if ($verified.Object.resource_server.policy_revision -cne $revision -or
    $verified.Object.tool_policy.files_stat.scope -cne 'files:read' -or
    $verified.Object.tool_policy.files_read.scope -cne 'files:read') { throw 'Prepared policy repair validation failed.' }
$id = [guid]::NewGuid().ToString('N')
$temp = $target + '.' + $id + '.tmp'
$backup = $target + '.' + $id + '.bak'
Assert-ZagentPlainPath $temp
Assert-ZagentPlainPath $backup
if ((Test-Path -LiteralPath $temp) -or (Test-Path -LiteralPath $backup)) { throw 'Migration artifact collision.' }
try {
    $stream = [IO.File]::Open($temp, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write, [IO.FileShare]::None)
    try { $stream.Write($bytes, 0, $bytes.Length); $stream.Flush($true) } finally { $stream.Dispose() }
    # New file initially inherits only the already-validated owner-private directory.
    Set-ZagentOwnerAcl $temp
    Assert-MigrationPrivatePath $configDir
    Assert-CoreStopped
    Assert-ReviewedMetadata
    Assert-SnapshotUnchanged $target $before
    # CAS-style recheck immediately before atomic replace. Core must remain stopped;
    # this is not a filesystem compare-and-swap against a hostile concurrent owner.
    [IO.File]::Replace($temp, $target, $backup)
    Assert-MigrationPrivatePath $target
    Assert-MigrationPrivatePath $backup
    $readback = Read-BoundedBytes $target
    if ([Convert]::ToBase64String($readback) -cne [Convert]::ToBase64String($bytes)) { throw 'Read-back mismatch; retain private backup and stop.' }
    $backupBytes = Read-BoundedBytes $backup
    if ([Convert]::ToBase64String($backupBytes) -cne [Convert]::ToBase64String($before)) { throw 'Backup mismatch; retain artifacts and stop.' }
    Assert-ReviewedMetadata
    Assert-CoreStopped
    Write-Host 'FILES_READ_POLICY_REPAIRED; exact read-back and backup verified; ALL grants/expiry/scopes preserved; authenticated Files call NOT_VERIFIED.'
    Write-Host ('Private configuration backup: ' + $backup)
    Write-Host 'Restart the existing enrollment with Start-OwnerCore.ps1. No grant renewal or OAuth login was performed.'
} catch {
    # Never automatically roll back, delete private artifacts, reprovision or start Core.
    Write-Host ('Migration stopped. Keep Core stopped; retain private artifacts if present: ' + $temp + ' ; ' + $backup)
    throw 'Files read-policy repair failed; keep Core stopped and retain private backup. No automatic recovery was attempted.'
}

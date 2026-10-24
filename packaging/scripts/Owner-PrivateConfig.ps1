# Shared bounded owner-private JSON/file checks copied from the reviewed migration helper.
# Dot-source only: no enrollment, runtime calls, file writes or secret decryption.
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
    $s = @{ Text = $utf8.GetString($Bytes); Index = 0; Nodes = 0; Clock = [Diagnostics.Stopwatch]::StartNew(); ResourceUri = $null; PolicyRevision = $null }
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
            if ($s.Index -lt $s.Text.Length -and $s.Text[$s.Index] -eq '}') { $s.Index++; return }
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
    }
    Skip-JsonSpace
    if ($s.Index -ge $s.Text.Length -or $s.Text[$s.Index] -ne '{') { throw 'JSON object required.' }
    Read-JsonValue 0 @()
    Skip-JsonSpace
    if ($s.Index -ne $s.Text.Length) { throw 'Trailing JSON data rejected.' }
    try { $object = ConvertFrom-Json -InputObject ($s.Text.TrimStart([char]0xFEFF)) }
    catch { throw 'Private JSON object conversion failed.' }
    return @{ Object = $object; Text = $s.Text; ResourceUri = $s.ResourceUri; PolicyRevision = $s.PolicyRevision }
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

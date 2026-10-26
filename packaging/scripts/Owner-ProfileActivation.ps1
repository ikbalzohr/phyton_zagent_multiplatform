# Dot-source library. No product imports, enrollment, credential reads or runtime calls.
# Requires WindowsDashboard-Provisioning.ps1 and Owner-PrivateConfig.ps1 in caller scope.
function Assert-ActivationId($Id) {
    if ($Id -isnot [string] -or $Id -cnotmatch '\A[A-Za-z0-9][A-Za-z0-9._-]{0,127}\z') { throw 'Invalid profile identifier.' }
}
function Assert-ActivationPath($Path, [switch]$Executable) {
    if ($Path -isnot [string] -or $Path.Length -gt 1024 -or
        $Path -cnotmatch '\A[A-Za-z]:\\[^<>:"/|?*%\x00-\x1f]+\z' -or
        $Path -match '(?:^|\\)\.{1,2}(?:\\|$)|[. ](?:\\|$)' -or
        [IO.Path]::GetFullPath($Path).TrimEnd('\') -ine $Path.TrimEnd('\')) { throw 'Bounded literal local path required; no expansion.' }
    Assert-ZagentPlainPath $Path
    if ($Executable) {
        if (-not (Test-Path -LiteralPath $Path -PathType Leaf) -or [IO.Path]::GetExtension($Path) -ine '.exe') { throw 'Existing native .exe required; batch wrappers are not adopted.' }
    } elseif (-not (Test-Path -LiteralPath $Path -PathType Container)) { throw 'Existing bounded directory required.' }
}
function ConvertTo-ActivationToken($Value) { return (ConvertTo-Json -InputObject $Value -Depth 64 -Compress) }
function Get-ActivationSpan([string]$Text, [string[]]$Path) {
    # Input is first strictly validated by the shared bounded parser. This scanner
    # only locates tokens; unchanged numeric/string values are never reserialized.
    $null = Read-StrictJson ($utf8.GetBytes($Text))
    $state = @{ i = 0; found = $null; nodes = 0; clock = [Diagnostics.Stopwatch]::StartNew() }
    function Skip-ActivationSpace { while ($state.i -lt $Text.Length -and (" `t`r`n" + [char]0xFEFF).IndexOf($Text[$state.i]) -ge 0) { $state.i++ } }
    function Walk-ActivationValue([string[]]$Here) {
        $state.nodes++
        if ($Here.Count -gt 64 -or $state.nodes -gt 32768 -or $state.clock.Elapsed.TotalSeconds -gt 15) { throw 'JSON token scan budget exceeded.' }
        Skip-ActivationSpace
        $start = $state.i
        $ch = $Text[$state.i]
        if ($ch -eq '{') {
            $state.i++; Skip-ActivationSpace
            if ($Text[$state.i] -ne '}') {
                while ($true) {
                    Skip-ActivationSpace
                    $m = [regex]::Match($Text.Substring($state.i), '\A"(?:[^"\\]|\\.)*"')
                    $key = [string](@(ConvertFrom-Json ('[' + $m.Value + ']'))[0])
                    $state.i += $m.Length; Skip-ActivationSpace; $state.i++
                    Walk-ActivationValue (@($Here) + @($key))
                    Skip-ActivationSpace
                    if ($Text[$state.i] -eq '}') { break }
                    $state.i++
                }
            }
            $state.i++
        } elseif ($ch -eq '[') {
            $state.i++; Skip-ActivationSpace; $index = 0
            if ($Text[$state.i] -ne ']') {
                while ($true) {
                    Walk-ActivationValue (@($Here) + @([string]$index)); $index++
                    Skip-ActivationSpace
                    if ($Text[$state.i] -eq ']') { break }
                    $state.i++
                }
            }
            $state.i++
        } else {
            $m = [regex]::Match($Text.Substring($state.i), '\A(?:"(?:[^"\\]|\\.)*"|true|false|null|-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?)')
            $state.i += $m.Length
        }
        if (($Here.Count -eq $Path.Count) -and ((@($Here) -join [char]0) -ceq (@($Path) -join [char]0))) {
            $state.found = @{ Start = $start; Length = $state.i - $start }
        }
    }
    Walk-ActivationValue @()
    if ($null -eq $state.found) { throw 'Required JSON path missing.' }
    return $state.found
}
function Replace-ActivationToken([string]$Text, [string[]]$Path, [string]$Token) {
    $span = Get-ActivationSpan $Text $Path
    $next = $Text.Remove($span.Start, $span.Length).Insert($span.Start, $Token)
    $null = Read-StrictJson ($utf8.GetBytes($next))
    return $next
}
function Get-ActivationToken([string]$Text, [string[]]$Path) {
    $span = Get-ActivationSpan $Text $Path
    return $Text.Substring($span.Start, $span.Length)
}
function Assert-ActivationApproved($Row, [switch]$AllowReadOnly) {
    foreach ($binding in @(@('device_id','7338141d-ab55-4d78-a97e-35336f970fb5'), @('installation_id','7c82db6b-f6f2-4072-bd38-7ed763aa45d3'))) {
        $property = $Row.PSObject.Properties[$binding[0]]
        if ($null -ne $property -and $property.Value -cne $binding[1]) { throw 'Local profile installation/device binding mismatch.' }
    }
    $modes = @('read-write')
    if ($AllowReadOnly) { $modes += 'read-only' }
    if ($Row -isnot [pscustomobject] -or $Row.enabled -isnot [bool] -or $Row.enabled -ne $true -or
        $Row.authorized_by_user -isnot [bool] -or $Row.authorized_by_user -ne $true -or $Row.mode -cnotin $modes) { throw 'Existing approved enabled profile with required mode needed.' }
    Assert-ActivationPath $Row.root
}
function Assert-ActivationPolicy($Policy, [string]$Id, $Rows, $Grant) {
    $keys = @('version','enabled','execution_mode','acknowledge_host_access','profile_id','root','allowed_tools','allowed_executables','max_timeout_seconds','max_output_chars')
    if ($Policy -isnot [pscustomobject] -or @($Policy.PSObject.Properties).Count -ne $keys.Count) { throw 'Invalid v1 command policy schema.' }
    foreach ($p in $Policy.PSObject.Properties) { if ($p.Name -cnotin $keys) { throw 'Unknown command policy key.' } }
    if ($Policy.version -isnot [int] -and $Policy.version -isnot [long]) { throw 'Integer policy version required.' }
    if ($Policy.version -ne 1 -or $Policy.profile_id -cne $Id -or $Policy.enabled -isnot [bool] -or $Policy.enabled -ne $true -or
        $Policy.acknowledge_host_access -isnot [bool] -or $Policy.acknowledge_host_access -ne $true -or $Policy.execution_mode -cne 'owner-account') { throw 'Explicit existing owner-account policy required.' }
    $row = $Rows[$Id]
    if ($null -eq $row) { throw 'Policy references missing local profile.' }
    Assert-ActivationApproved $row
    Assert-ActivationPath $Policy.root
    if ($Policy.root.TrimEnd('\') -ine $row.root.TrimEnd('\')) { throw 'Command policy root mismatch.' }
    foreach ($pair in @(@('max_timeout_seconds',1800), @('max_output_chars',200000))) {
        $value = $Policy.($pair[0])
        if (($value -isnot [int] -and $value -isnot [long]) -or $value -lt 1 -or $value -gt $pair[1]) { throw 'Invalid bounded command limit.' }
    }
    $supported = @('files_command_capabilities','files_command_cancel','files_exec_command','files_powershell_run','files_node','files_npm','files_npx','files_git','files_build','files_test','files_process_list','files_process_stop')
    if ($Policy.allowed_tools -isnot [array] -or $Policy.allowed_tools.Count -lt 1 -or $Policy.allowed_tools.Count -gt $supported.Count) { throw 'Bounded command tools required.' }
    $seen = [Collections.Generic.HashSet[string]]::new([StringComparer]::Ordinal)
    foreach ($tool in $Policy.allowed_tools) {
        if ($tool -isnot [string] -or $tool -cnotin $supported -or -not $seen.Add($tool)) { throw 'Unsupported/duplicate command tool.' }
        if ($Id -ceq 'agentRoot' -and $tool -cnotin $Grant.tools) { throw 'Existing grant does not allow migrated command tool.' }
    }
    if ($Policy.allowed_executables -isnot [array] -or $Policy.allowed_executables.Count -lt 1 -or $Policy.allowed_executables.Count -gt 64) { throw 'Bounded executable list required.' }
    $seen = [Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase)
    foreach ($exe in $Policy.allowed_executables) {
        Assert-ActivationPath $exe -Executable
        if (-not $seen.Add($exe)) { throw 'Duplicate executable.' }
    }
}
function New-OwnerProfileActivationPlan([byte[]]$ProfileBytes, [byte[]]$CommandBytes, [byte[]]$TunnelBytes,
    [string]$ExpectedRoot, [string]$LegacyRoot, [string[]]$AllowedProfileIds = @('agentRoot')) {
    $pp = Read-StrictJson $ProfileBytes; $cp = Read-StrictJson $CommandBytes; $tp = Read-StrictJson $TunnelBytes
    $profiles = $pp.Object; $command = $cp.Object; $tunnel = $tp.Object
    if ($profiles.profiles -isnot [array] -or $profiles.profiles.Count -lt 1 -or $profiles.profiles.Count -gt 128 -or
        $null -eq $profiles.PSObject.Properties['active_profile']) { throw 'Invalid local profiles document.' }
    $rows = [Collections.Generic.Dictionary[string,object]]::new([StringComparer]::Ordinal)
    $caseNames = [Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase)
    foreach ($row in $profiles.profiles) {
        Assert-ActivationId $row.name
        if (-not $caseNames.Add($row.name)) { throw 'Duplicate/ambiguous local profile.' }
        $rows.Add($row.name, $row)
    }
    if (-not $rows.ContainsKey('agentRoot')) { throw 'Existing agentRoot approval missing; never synthesize approval.' }
    Assert-ActivationApproved $rows['agentRoot']
    if ($rows['agentRoot'].root.TrimEnd('\') -ine $ExpectedRoot.TrimEnd('\')) { throw 'Exact agentRoot root mismatch.' }
    if ($rows.ContainsKey('appBridge') -and $rows['appBridge'].root.TrimEnd('\') -ine $LegacyRoot.TrimEnd('\')) { throw 'Exact legacy root mismatch.' }
    if ($null -eq $AllowedProfileIds -or $AllowedProfileIds.Count -lt 1 -or $AllowedProfileIds.Count -gt 128) { throw 'Nonempty bounded allowed profile list required.' }
    $allowed = [Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase)
    foreach ($id in $AllowedProfileIds) {
        Assert-ActivationId $id
        if ($id -ceq 'appBridge' -or -not $allowed.Add($id) -or -not $rows.ContainsKey($id)) { throw 'Removed/duplicate/unknown profile in requested allowlist.' }
        Assert-ActivationApproved $rows[$id] -AllowReadOnly
    }
    if ('agentRoot' -cnotin $AllowedProfileIds) { throw 'Allowlist must contain default agentRoot.' }
    $rs = $tunnel.resource_server
    $principal = 'principal_v1_41d40891edc920d08c8bf7d58f508bb1a082a9dc8dc5bb70f4fa2d913161a59d'
    $issuer = 'https://vmi3669591.contaboserver.net/realms/zagent'
    if ($rs.issuer -cne $issuer -or $rs.resource_uri -cne 'https://zagent.ikbalzohr.web.id/mcp' -or
        $rs.workspace_id -cne 'workspace-local' -or $rs.introspection_client_id -cne 'zagent-resource-server' -or
        $rs.introspection_endpoint -cne ($issuer + '/protocol/openid-connect/token/introspect')) { throw 'Trusted OAuth/workspace binding mismatch.' }
    $grant = $rs.grants.PSObject.Properties[$principal].Value
    $binding = $grant.files_resource
    if ($grant.revoked -isnot [bool] -or $grant.revoked -ne $false -or $binding.revoked -isnot [bool] -or $binding.revoked -ne $false -or
        ($grant.expires_at -isnot [int] -and $grant.expires_at -isnot [long]) -or $grant.expires_at -ne 1793539666 -or
        $grant.expires_at -le [DateTimeOffset]::UtcNow.ToUnixTimeSeconds() -or
        $binding.kind -cne 'files' -or $binding.profile_id -cnotin @('appBridge','agentRoot') -or
        $binding.resource_id -cne 'workspace:workspace-local:approved-repository' -or
        $binding.device_id -cne '7338141d-ab55-4d78-a97e-35336f970fb5' -or
        $binding.installation_id -cne '7c82db6b-f6f2-4072-bd38-7ed763aa45d3') { throw 'Existing finite active owner grant binding mismatch; no renewal.' }
    if ($grant.tools -isnot [array] -or $grant.scopes -isnot [array] -or 'files:write' -cnotin $grant.scopes -or 'files:execute' -cnotin $grant.scopes) { throw 'Existing execute/write grant required; no expansion.' }
    $oldAllow = $binding.PSObject.Properties['allowed_profile_ids']
    if ($null -ne $oldAllow) {
        if ($oldAllow.Value -isnot [array] -or $oldAllow.Value.Count -lt 1 -or $oldAllow.Value.Count -gt 128 -or $binding.profile_id -cnotin $oldAllow.Value) { throw 'Malformed existing profile allowlist.' }
        $seen = [Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase)
        foreach ($id in $oldAllow.Value) {
            Assert-ActivationId $id
            if (-not $seen.Add($id) -or -not $rows.ContainsKey($id)) { throw 'Duplicate/unknown existing allowed profile.' }
        }
    }
    $policyTexts = [ordered]@{}
    if ($command.version -eq 1) {
        Assert-ActivationPolicy $command $command.profile_id $rows $grant
        $policyTexts[$command.profile_id] = $cp.Text.TrimStart([char]0xFEFF)
    } elseif ($command.version -eq 2 -and @($command.PSObject.Properties).Count -eq 2 -and $null -ne $command.PSObject.Properties['profiles'] -and $command.profiles -is [pscustomobject]) {
        foreach ($property in $command.PSObject.Properties) { if ($property.Name -cnotin @('version','profiles')) { throw 'Unknown v2 envelope key.' } }
        if (($command.version -isnot [int] -and $command.version -isnot [long]) -or @($command.profiles.PSObject.Properties).Count -lt 1 -or @($command.profiles.PSObject.Properties).Count -gt 128) { throw 'Invalid v2 policy count/version.' }
        foreach ($property in $command.profiles.PSObject.Properties) {
            Assert-ActivationId $property.Name
            Assert-ActivationPolicy $property.Value $property.Name $rows $grant
            $policyTexts[$property.Name] = Get-ActivationToken $cp.Text @('profiles',$property.Name)
        }
    } else { throw 'Exact v1 or {version:2,profiles:{...}} policy required.' }
    if (-not $policyTexts.Contains('agentRoot')) {
        if (-not $policyTexts.Contains('appBridge')) { throw 'No existing bounded executable policy to reuse.' }
        $selected = Replace-ActivationToken $policyTexts['appBridge'] @('profile_id') '"agentRoot"'
        $selected = Replace-ActivationToken $selected @('root') (ConvertTo-ActivationToken $ExpectedRoot)
        $policyTexts['agentRoot'] = $selected
    }
    $policyTexts.Remove('appBridge')
    $selectedPolicy = (Read-StrictJson ($utf8.GetBytes($policyTexts['agentRoot']))).Object
    Assert-ActivationPolicy $selectedPolicy 'agentRoot' $rows $grant
    # Preserve original row tokens, including unknown fields/large numeric literals.
    $keptRows = @()
    for ($i = 0; $i -lt $profiles.profiles.Count; $i++) {
        if ($profiles.profiles[$i].name -cne 'appBridge') { $keptRows += Get-ActivationToken $pp.Text @('profiles',[string]$i) }
    }
    $nextProfiles = Replace-ActivationToken $pp.Text @('profiles') ('[' + ($keptRows -join ',') + ']')
    $nextProfiles = Replace-ActivationToken $nextProfiles @('active_profile') '"agentRoot"'
    $pairs = @()
    foreach ($id in $policyTexts.Keys) { $pairs += (ConvertTo-ActivationToken $id) + ':' + $policyTexts[$id] }
    # Exact v2 envelope; each value is the original v1 object (not a new schema).
    $envelope = [ordered]@{ version = 2; profiles = $null }
    $nextCommands = '{"version":' + $envelope.version + ',"profiles":{' + ($pairs -join ',') + '}}'
    $bindingPath = @('resource_server','grants',$principal,'files_resource')
    $nextTunnel = Replace-ActivationToken $tp.Text ($bindingPath + @('profile_id')) '"agentRoot"'
    $allowToken = ConvertTo-ActivationToken @($AllowedProfileIds)
    if ($null -ne $oldAllow) { $nextTunnel = Replace-ActivationToken $nextTunnel ($bindingPath + @('allowed_profile_ids')) $allowToken }
    else {
        $span = Get-ActivationSpan $nextTunnel $bindingPath
        $nextTunnel = $nextTunnel.Insert(($span.Start + $span.Length - 1), (',"allowed_profile_ids":' + $allowToken))
    }
    $null = Read-StrictJson ($utf8.GetBytes($nextProfiles))
    $null = Read-StrictJson ($utf8.GetBytes($nextCommands))
    $null = Read-StrictJson ($utf8.GetBytes($nextTunnel))
    if ($utf8.GetByteCount($nextCommands) -gt 262144 -or $utf8.GetByteCount($nextProfiles) -gt 262144 -or $utf8.GetByteCount($nextTunnel) -gt 1048576) { throw 'Candidate exceeds consumer JSON budget.' }
    return @{ Profiles = $utf8.GetBytes($nextProfiles); Commands = $utf8.GetBytes($nextCommands); Grant = $utf8.GetBytes($nextTunnel); Executables = @($selectedPolicy.allowed_executables); Timeout = $selectedPolicy.max_timeout_seconds; Output = $selectedPolicy.max_output_chars; Tools = @($selectedPolicy.allowed_tools) }
}
function New-ActivationArtifact([string]$Path, [byte[]]$Bytes) {
    Assert-CoreStopped
    Assert-MigrationPrivatePath ([IO.Path]::GetDirectoryName($Path))
    Assert-ZagentPlainPath $Path
    $stream = [IO.File]::Open($Path, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write, [IO.FileShare]::None)
    try { $stream.Write($Bytes, 0, $Bytes.Length); $stream.Flush($true) } finally { $stream.Dispose() }
    Set-ZagentOwnerAcl $Path
    Assert-SnapshotUnchanged $Path $Bytes
}
function Invoke-OwnerProfileActivationCommit($Entries) {
    # No hook parameters, process launch, rollback or physical project writes.
    # Concurrent configuration change is rejected by the shared snapshot guard.
    # PREPARE ALL candidates and independent exact backups before ANY replacement.
    $prepared = @(); $completed = @()
    try {
        Assert-CoreStopped
        # Validate EVERY input before creating even a staging artifact.
        foreach ($name in @('profiles','commands','grant')) {
            $entry = $Entries[$name]
            $null = Read-StrictJson $entry.Next
            $null = Read-StrictJson $entry.Before
            Assert-SnapshotUnchanged $entry.Path $entry.Before
        }
        foreach ($name in @('profiles','commands','grant')) {
            $entry = $Entries[$name]
            $tag = [guid]::NewGuid().ToString('N')
            $temp = $entry.Path + '.' + $tag + '.tmp'
            $backup = $entry.Path + '.' + $tag + '.bak'
            Assert-ZagentPlainPath ($temp + '.replaced')
            if (Test-Path -LiteralPath ($temp + '.replaced')) { throw 'Recovery artifact collision.' }
            Write-Host ('STAGING ' + $name + '; target=' + $entry.Path + '; candidate=' + $temp + '; backup=' + $backup)
            New-ActivationArtifact $temp $entry.Next
            New-ActivationArtifact $backup $entry.Before
            $prepared += @{ Name = $name; Path = $entry.Path; Before = $entry.Before; Next = $entry.Next; Temp = $temp; Backup = $backup }
            Write-Host ('PREPARED ' + $name + '; backup=' + $backup + '; candidate=' + $temp)
        }
        foreach ($p in $prepared) {
            Assert-SnapshotUnchanged $p.Path $p.Before
            Assert-SnapshotUnchanged $p.Backup $p.Before
            Assert-SnapshotUnchanged $p.Temp $p.Next
        }
        # COMMIT: grant last; individual replacements are NOT a multi-file transaction.
        foreach ($p in $prepared) {
            Assert-CoreStopped
            if ([DateTimeOffset]::UtcNow.ToUnixTimeSeconds() -ge 1793539666) { throw 'Grant expired during replacement; no renewal; keep Core stopped.' }
            Assert-ZagentPlainPath ($p.Temp + '.replaced')
            if (Test-Path -LiteralPath ($p.Temp + '.replaced')) { throw 'Recovery artifact appeared concurrently.' }
            foreach ($other in $prepared) {
                if ($other.Name -cin $completed) { Assert-SnapshotUnchanged $other.Path $other.Next }
                else { Assert-SnapshotUnchanged $other.Path $other.Before }
                Assert-SnapshotUnchanged $other.Backup $other.Before
                if ($other.Name -cin $completed) { Assert-SnapshotUnchanged ($other.Temp + '.replaced') $other.Before }
                else { Assert-SnapshotUnchanged $other.Temp $other.Next }
            }
            # Temp receives old target as a second recovery copy; original backup stays intact.
            [IO.File]::Replace($p.Temp, $p.Path, ($p.Temp + '.replaced'))
            $completed += $p.Name
            Assert-SnapshotUnchanged $p.Path $p.Next
            Assert-SnapshotUnchanged $p.Backup $p.Before
            Assert-SnapshotUnchanged ($p.Temp + '.replaced') $p.Before
            Write-Host ('VERIFIED ' + $p.Name + '; backup=' + $p.Backup)
        }
        Assert-CoreStopped
        foreach ($p in $prepared) { Assert-SnapshotUnchanged $p.Path $p.Next; Assert-SnapshotUnchanged $p.Backup $p.Before }
        Write-Host 'OWNER_PROFILE_ACTIVATED; exact read-back and backups verified. Core remains stopped. Windows/remote behavior is a separate gate.'
    } catch {
        Write-Host ('ACTIVATION_INCOMPLETE; verified replacements=' + ($completed -join ',') + '. Keep Core stopped; retain every .bak/.tmp/.replaced artifact; no auto rollback or restart.')
        throw
    }
}

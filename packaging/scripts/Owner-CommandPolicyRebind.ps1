# Bounded owner-local command policy rebind to an existing approved agentRoot.
# Dot-source only: no enrollment, runtime calls, process launch, secret reads or ACL writes.
# Touches ONLY profile_id and root tokens of the existing command policy entry; all
# authority limits (expires_at/revocation, scopes, tools, tool_policy, limits, executables)
# are preserved and proven byte-for-byte. v1 and v2 formats supported exactly as parsed.
$utf8 = [Text.UTF8Encoding]::new($false, $true)
$script:idPattern = '\A[A-Za-z0-9_-]{1,256}\z'
$script:policyKeys = @('acknowledge_host_access','allowed_executables','allowed_tools','enabled','execution_mode','max_output_chars','max_timeout_seconds','profile_id','root','version')
function Get-CommandPolicyKeySpan([string]$Text, [string]$Id) {
    $value = Get-ProfileAdminSpan $Text @('profiles',$Id)
    $prefix = $Text.Substring(0,$value.Start)
    $match = [regex]::Match($prefix, '"(?:[^"\\\x00-\x1f]|\\(?:["\\/bfnrt]|u[0-9a-fA-F]{4}))*"\s*:\s*\z')
    if (-not $match.Success) { throw 'Policy map key span not found.' }
    $token = $match.Value.Substring(0,$match.Value.LastIndexOf(':')).TrimEnd()
    $decoded = @(ConvertFrom-Json -InputObject ('['+$token+']'))[0]
    if ($decoded -cne $Id) { throw 'Policy map key span mismatch.' }
    return @{ Start=$match.Index; Length=$token.Length }
}
function Test-NormalizedRoot([string]$A, [string]$B) {
    if ($null -eq $A -or $null -eq $B) { return $false }
    return ($A.TrimEnd('\') -ceq $B.TrimEnd('\'))
}
function Test-IntegerType([object]$v) {
    return ($v -is [int] -or $v -is [long] -or $v -is [short] -or $v -is [byte] -or $v -is [sbyte] -or $v -is [uint16] -or $v -is [uint32] -or $v -is [uint64])
}
function Test-TrueFlag([object]$v) {
    return ($v -is [bool] -and $v -eq $true)
}
function Get-OwnerCommandPolicySummary([byte[]]$PolicyBytes) {
    if ($PolicyBytes.Length -lt 2 -or $PolicyBytes.Length -gt 262144) { throw 'Command policy size outside 2..262144 bytes.' }
    $document = (Read-StrictJson $PolicyBytes).Object
    if (-not (Test-IntegerType $document.version)) { throw 'INVALID_COMMAND_POLICY_SCHEMA' }
    $keys = [Collections.Generic.HashSet[string]]::new([StringComparer]::Ordinal)
    foreach ($property in $document.PSObject.Properties) { $null=$keys.Add($property.Name) }
    $expected = [Collections.Generic.HashSet[string]]::new([StringComparer]::Ordinal)
    foreach ($key in $script:policyKeys) { $null=$expected.Add($key) }
    if ($document.version -eq 1 -and $expected.SetEquals($keys)) { $entries=@($document) }
    elseif ($document.version -eq 2 -and $keys.Count -eq 2 -and $keys.Contains('version') -and $keys.Contains('profiles') -and $document.profiles -is [pscustomobject]) {
        $entries=@($document.profiles.PSObject.Properties | ForEach-Object {
            if ($_.Name -cne $_.Value.profile_id) { throw 'COMMAND_POLICY_PROFILE_MISMATCH' }
            $_.Value
        })
    } else { throw 'INVALID_COMMAND_POLICY_SCHEMA' }
    if ($entries.Count -lt 1 -or $entries.Count -gt 128) { throw 'INVALID_COMMAND_POLICY_PROFILES' }
    foreach ($entry in $entries) {
        $entryKeys=[Collections.Generic.HashSet[string]]::new([StringComparer]::Ordinal)
        foreach ($property in $entry.PSObject.Properties) { $null=$entryKeys.Add($property.Name) }
        if (-not $expected.SetEquals($entryKeys) -or -not (Test-IntegerType $entry.version) -or $entry.version -ne 1) { throw 'INVALID_COMMAND_POLICY_SCHEMA' }
        [pscustomobject]@{ profile_id=$entry.profile_id; root=$entry.root; enabled=$entry.enabled;
            acknowledge_host_access=$entry.acknowledge_host_access; execution_mode=$entry.execution_mode;
            allowed_tools=$entry.allowed_tools; allowed_executables=$entry.allowed_executables;
            max_timeout_seconds=$entry.max_timeout_seconds; max_output_chars=$entry.max_output_chars }
    }
}
function New-OwnerCommandPolicyRebindPlan([byte[]]$PolicyBytes, [byte[]]$ProfilesBytes, [string]$SourceProfileId, [string]$SourceRoot, [switch]$AllowRemovedSourceProfile) {
    foreach ($value in @($SourceProfileId,$SourceRoot)) {
        if ([string]::IsNullOrWhiteSpace($value) -or $value.Length -gt 260 -or $value -match '[\x00-\x1f]') { throw 'Explicit bounded source placement required.' }
    }
    if ($PolicyBytes.Length -lt 2 -or $PolicyBytes.Length -gt 262144) { throw 'Command policy size outside 2..262144 bytes.' }
    if ($ProfilesBytes.Length -lt 2 -or $ProfilesBytes.Length -gt 262144) { throw 'Local profiles size outside 2..262144 bytes.' }
    $parsedPolicy = Read-StrictJson $PolicyBytes
    $parsedProfiles = Read-StrictJson $ProfilesBytes
    $plan = $parsedPolicy.Object
    $version = $plan.version
    if ($version -is [bool] -or -not (Test-IntegerType $version) -or ($version -ne 1 -and $version -ne 2)) { throw 'INVALID_COMMAND_POLICY_SCHEMA' }
    $policyKeySet = [Collections.Generic.HashSet[string]]::new([StringComparer]::Ordinal)
    foreach ($k in $script:policyKeys) { $null = $policyKeySet.Add($k) }
    $sourceEntry = $null; $sourcePath = @()
    if ($version -eq 1) {
        $nameSet = [Collections.Generic.HashSet[string]]::new([StringComparer]::Ordinal)
        foreach ($p in $plan.PSObject.Properties) { $null = $nameSet.Add($p.Name) }
        if (-not $policyKeySet.SetEquals($nameSet)) { throw 'INVALID_COMMAND_POLICY_SCHEMA' }
        $sourceEntry = $plan
        $sourcePath = @()
    } elseif ($version -eq 2) {
        $nameSet = [Collections.Generic.HashSet[string]]::new([StringComparer]::Ordinal)
        foreach ($p in $plan.PSObject.Properties) { $null = $nameSet.Add($p.Name) }
        $v2KeySet = [Collections.Generic.HashSet[string]]::new([StringComparer]::Ordinal)
        $null = $v2KeySet.Add('version'); $null = $v2KeySet.Add('profiles')
        if (-not $v2KeySet.SetEquals($nameSet)) { throw 'INVALID_COMMAND_POLICY_SCHEMA' }
        $profiles = $plan.profiles
        if ($profiles -isnot [pscustomobject] -or (@($profiles.PSObject.Properties)).Count -lt 1 -or (@($profiles.PSObject.Properties)).Count -gt 128) { throw 'INVALID_COMMAND_POLICY_PROFILES' }
        $idSet = [Collections.Generic.HashSet[string]]::new([StringComparer]::Ordinal)
        foreach ($entry in $profiles.PSObject.Properties) {
            $id = $entry.Name
            if ($id -cnotmatch $script:idPattern -or -not $idSet.Add($id)) { throw 'INVALID_COMMAND_POLICY_PROFILE_ID' }
            $member = $entry.Value
            if ($member -isnot [pscustomobject]) { throw 'INVALID_COMMAND_POLICY_SCHEMA' }
            $memberNameSet = [Collections.Generic.HashSet[string]]::new([StringComparer]::Ordinal)
            foreach ($m in $member.PSObject.Properties) { $null = $memberNameSet.Add($m.Name) }
            if (-not $policyKeySet.SetEquals($memberNameSet)) { throw 'INVALID_COMMAND_POLICY_SCHEMA' }
            if (-not (Test-IntegerType $member.version) -or $member.version -ne 1 -or $member.profile_id -cne $id) { throw 'COMMAND_POLICY_PROFILE_MISMATCH' }
        }
        $sourceProp = $profiles.PSObject.Properties[$SourceProfileId]
        if ($null -eq $sourceProp) { throw 'Source profile absent; no rebind performed.' }
        $sourceEntry = $sourceProp.Value
        $sourcePath = @('profiles',$SourceProfileId)
    } else { throw 'INVALID_COMMAND_POLICY_SCHEMA' }
    if ($sourceEntry.profile_id -cne $SourceProfileId) { throw 'Source profile_id mismatch: entry not v1 self-describing.' }
    if (-not (Test-TrueFlag $sourceEntry.enabled) -or -not (Test-TrueFlag $sourceEntry.acknowledge_host_access) -or $sourceEntry.execution_mode -cne 'owner-account') { throw 'Source profile lacks explicit owner-account approval; no rebind performed.' }
    if (-not (Test-NormalizedRoot $sourceEntry.root $SourceRoot)) { throw 'Source root not supplied exactly; refusing guessed binding.' }
    $profilesDoc = $parsedProfiles.Object
    if ($profilesDoc -isnot [pscustomobject] -or $profilesDoc.profiles -isnot [array]) { throw 'INVALID_LOCAL_PROFILES' }
    $rows = $profilesDoc.profiles
    if ($rows.Count -lt 1 -or $rows.Count -gt 128) { throw 'INVALID_LOCAL_PROFILES' }
    $sourceMatches = @($rows | Where-Object { $_.name -ceq $SourceProfileId })
    if ($sourceMatches.Count -gt 1) { throw 'Duplicate source profile; no rebind performed.' }
    if ($sourceMatches.Count -eq 0 -and -not $AllowRemovedSourceProfile) { throw 'Source profile absent from local profiles.json; explicit removed-source migration required.' }
    if ($sourceMatches.Count -eq 1) {
        $sourceProfile = $sourceMatches[0]
        if (-not (Test-TrueFlag $sourceProfile.enabled) -or -not (Test-TrueFlag $sourceProfile.authorized_by_user) -or $sourceProfile.mode -cne 'read-write') { throw 'Source profile not locally approved read-write; no rebind performed.' }
        if (-not (Test-NormalizedRoot $sourceProfile.root $SourceRoot)) { throw 'Source profile root mismatch; no rebind performed.' }
    }
    $targetMatches = @($rows | Where-Object { $_.name -ceq 'agentRoot' })
    if ($targetMatches.Count -ne 1) { throw 'Target agentRoot profile not locally approved read-write; no rebind performed.' }
    $targetProfile = $targetMatches[0]
    if (-not (Test-TrueFlag $targetProfile.enabled) -or -not (Test-TrueFlag $targetProfile.authorized_by_user) -or $targetProfile.mode -cne 'read-write') { throw 'Target agentRoot profile not locally approved read-write; no rebind performed.' }
    $targetRoot = [string]$targetProfile.root
    if ([string]::IsNullOrWhiteSpace($targetRoot) -or $targetRoot.Length -gt 260 -or $targetRoot -match '[\x00-\x1f]') { throw 'Target agentRoot root invalid; no rebind performed.' }
    if ($SourceProfileId -ceq 'agentRoot') { throw 'Refusing preexisting target conflicting policy; no rebind performed.' }
    if ($version -eq 2 -and $null -ne $plan.profiles.PSObject.Properties['agentRoot']) { throw 'Target agentRoot already present in command policy; explicit review required.' }
    $text = $parsedPolicy.Text
    $newProfileToken = (ConvertTo-Json -InputObject 'agentRoot' -Compress)
    $newRootToken = (ConvertTo-Json -InputObject $targetRoot -Compress)
    $idSpan = Get-ProfileAdminSpan $text ($sourcePath + @('profile_id'))
    $idBefore = $text.Substring($idSpan.Start, $idSpan.Length)
    $text1 = $text.Remove($idSpan.Start, $idSpan.Length).Insert($idSpan.Start, $newProfileToken)
    $rootSpan = Get-ProfileAdminSpan $text1 ($sourcePath + @('root'))
    $rootBefore = $text1.Substring($rootSpan.Start, $rootSpan.Length)
    $text2 = $text1.Remove($rootSpan.Start, $rootSpan.Length).Insert($rootSpan.Start, $newRootToken)
    $keyBefore = $null
    if ($version -eq 2) {
        $keySpan = Get-CommandPolicyKeySpan $text2 $SourceProfileId
        $keyBefore = $text2.Substring($keySpan.Start,$keySpan.Length)
        $text2 = $text2.Remove($keySpan.Start,$keySpan.Length).Insert($keySpan.Start,$newProfileToken)
    }
    $next = $utf8.GetBytes($text2)
    $check = Read-StrictJson $next
    $verify = if ($version -eq 1) { $check.Object } else { $check.Object.profiles.agentRoot }
    if ($verify.profile_id -cne 'agentRoot' -or (Test-NormalizedRoot $verify.root $targetRoot) -eq $false -or $verify.version -ne 1 -or -not (Test-TrueFlag $verify.enabled)) { throw 'Rebind validation failed; no write performed.' }
    $reverse = $text2
    if ($version -eq 2) {
        $keySpanBack = Get-CommandPolicyKeySpan $reverse 'agentRoot'
        $reverse = $reverse.Remove($keySpanBack.Start,$keySpanBack.Length).Insert($keySpanBack.Start,$keyBefore)
    }
    $rootSpanBack = Get-ProfileAdminSpan $reverse ($sourcePath + @('root'))
    $reverse = $reverse.Remove($rootSpanBack.Start, $rootSpanBack.Length).Insert($rootSpanBack.Start, $rootBefore)
    $idSpanBack = Get-ProfileAdminSpan $reverse ($sourcePath + @('profile_id'))
    $reverse = $reverse.Remove($idSpanBack.Start, $idSpanBack.Length).Insert($idSpanBack.Start, $idBefore)
    if ([Convert]::ToBase64String($utf8.GetBytes($reverse)) -cne [Convert]::ToBase64String($PolicyBytes)) { throw 'Unrelated configuration bytes changed; no write performed.' }
    return [pscustomobject]@{ Bytes = $next; ProfileId = 'agentRoot'; Root = $targetRoot; SourceProfileId = $SourceProfileId }
}

# Pure capability plan utilities. Caller loads Owner-PrivateConfig.ps1 first.
function Assert-ProfileAdminCoreStopped {
    # Reject ALL Core executables, regardless of path. A dotnet host can own Core;
    # do not interpret or log potentially secret command lines to guess ownership.
    $processes = @(Get-CimInstance Win32_Process -Filter "Name='Zagent.Core.exe' OR Name='dotnet.exe' OR Name='dotnet'" -ErrorAction Stop)
    if ($processes.Count -ne 0) { throw 'Core executable or ambiguous dotnet host is running; no write allowed.' }
}
function Get-ProfileAdminSpan([string]$Text, [string[]]$Path) {
    $null = Read-StrictJson ($utf8.GetBytes($Text))
    $state = @{ i = 0; found = $null; nodes = 0; clock = [Diagnostics.Stopwatch]::StartNew() }
    function Skip-ProfileAdminSpace { while ($state.i -lt $Text.Length -and (" `t`r`n" + [char]0xFEFF).IndexOf($Text[$state.i]) -ge 0) { $state.i++ } }
    function Walk-ProfileAdminValue([string[]]$Here) {
        $state.nodes++
        if ($Here.Count -gt 64 -or $state.nodes -gt 32768 -or $state.clock.Elapsed.TotalSeconds -gt 15) { throw 'JSON span budget exceeded.' }
        Skip-ProfileAdminSpace; $start = $state.i; $ch = $Text[$state.i]
        if ($ch -eq '{') {
            $state.i++; Skip-ProfileAdminSpace
            if ($Text[$state.i] -ne '}') {
                while ($true) {
                    Skip-ProfileAdminSpace
                    $m = [regex]::Match($Text.Substring($state.i), '\A"(?:[^"\\]|\\.)*"')
                    $key = [string](@(ConvertFrom-Json ('[' + $m.Value + ']'))[0])
                    $state.i += $m.Length; Skip-ProfileAdminSpace; $state.i++
                    Walk-ProfileAdminValue (@($Here) + @($key)); Skip-ProfileAdminSpace
                    if ($Text[$state.i] -eq '}') { break }; $state.i++
                }
            }; $state.i++
        } elseif ($ch -eq '[') {
            $state.i++; Skip-ProfileAdminSpace; $index = 0
            if ($Text[$state.i] -ne ']') {
                while ($true) {
                    Walk-ProfileAdminValue (@($Here) + @([string]$index)); $index++; Skip-ProfileAdminSpace
                    if ($Text[$state.i] -eq ']') { break }; $state.i++
                }
            }; $state.i++
        } else {
            $m = [regex]::Match($Text.Substring($state.i), '\A(?:"(?:[^"\\]|\\.)*"|true|false|null|-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?)')
            $state.i += $m.Length
        }
        if ($Here.Count -eq $Path.Count -and (@($Here) -join [char]0) -ceq (@($Path) -join [char]0)) { $state.found = @{ Start=$start; Length=$state.i-$start } }
    }
    Walk-ProfileAdminValue @()
    if ($null -eq $state.found) { throw 'Required JSON path absent.' }
    return $state.found
}
function Set-ProfileAdminMember([string]$Text, [string[]]$Parent, [string]$Name, [string]$Token) {
    $parsed = (Read-StrictJson ($utf8.GetBytes($Text))).Object
    $object = $parsed
    foreach ($part in $Parent) { $object = $object.PSObject.Properties[$part].Value }
    if ($object -isnot [pscustomobject]) { throw 'JSON object required for capability patch.' }
    if ($null -ne $object.PSObject.Properties[$Name]) {
        $span = Get-ProfileAdminSpan $Text (@($Parent) + @($Name))
        $next = $Text.Remove($span.Start,$span.Length).Insert($span.Start,$Token)
    } else {
        $span = Get-ProfileAdminSpan $Text $Parent
        $separator = ''; if (@($object.PSObject.Properties).Count -gt 0) { $separator = ',' }
        $key = ConvertTo-Json -InputObject $Name -Compress
        $next = $Text.Insert(($span.Start+$span.Length-1), ($separator+$key+':'+$Token))
    }
    $null = Read-StrictJson ($utf8.GetBytes($next)); return $next
}
function New-ProfileAdministrationPlan([byte[]]$Before, [string]$OwnerPrincipal, [string]$WorkspaceId,
    [string]$DeviceId, [string]$InstallationId, [long]$Now = ([DateTimeOffset]::UtcNow.ToUnixTimeSeconds())) {
    foreach ($value in @($OwnerPrincipal,$WorkspaceId,$DeviceId,$InstallationId)) {
        if ([string]::IsNullOrWhiteSpace($value) -or $value.Length -gt 256 -or $value -match '[\x00-\x1f]') { throw 'Explicit bounded owner placement required.' }
    }
    $parsed = Read-StrictJson $Before; $config = $parsed.Object; $rs = $config.resource_server
    if ($config -isnot [pscustomobject] -or $rs -isnot [pscustomobject] -or
        $rs.workspace_id -isnot [string] -or $rs.workspace_id -cne $WorkspaceId -or $rs.grants -isnot [pscustomobject]) { throw 'Existing trusted workspace/grants required.' }
    $property = $rs.grants.PSObject.Properties[$OwnerPrincipal]
    if ($null -eq $property) { throw 'Explicit owner principal has no existing grant.' }
    $grant = $property.Value; $resource = $grant.files_resource
    if ($grant -isnot [pscustomobject] -or $resource -isnot [pscustomobject] -or
        $grant.revoked -isnot [bool] -or $grant.revoked -ne $false -or
        ($grant.expires_at -isnot [int] -and $grant.expires_at -isnot [long]) -or $grant.expires_at -le $Now -or
        $resource.revoked -isnot [bool] -or $resource.revoked -ne $false -or $resource.kind -isnot [string] -or $resource.kind -cne 'files' -or
        $resource.device_id -isnot [string] -or $resource.device_id -cne $DeviceId -or
        $resource.installation_id -isnot [string] -or $resource.installation_id -cne $InstallationId -or
        $resource.resource_id -isnot [string] -or [string]::IsNullOrWhiteSpace($resource.resource_id) -or $resource.resource_id.Length -gt 256) { throw 'Existing finite active owner grant/resource placement required; no renewal or identity change.' }
    if ($resource.profile_id -isnot [string]) { throw 'Existing default must be an exact string identifier.' }
    $defaultId = $resource.profile_id
    $membershipProperty = $resource.PSObject.Properties['allowed_profile_ids']
    $membership = @($defaultId)
    if ($null -ne $membershipProperty) { $membership = $membershipProperty.Value }
    if ($membership -isnot [array] -or $membership.Count -lt 1 -or $membership.Count -gt 128 -or $defaultId -cnotin $membership) { throw 'Existing bounded resource membership/default required.' }
    $seen = [Collections.Generic.HashSet[string]]::new([StringComparer]::Ordinal)
    foreach ($id in $membership) {
        if ($id -isnot [string] -or $id -cnotmatch '\A[A-Za-z0-9_-]{1,256}\z' -or -not $seen.Add($id)) { throw 'Invalid/duplicate existing resource profile identifier.' }
    }
    if ($grant.scopes -isnot [array] -or $grant.scopes.Count -gt 128 -or 'files:read' -cnotin $grant.scopes -or 'files:write' -cnotin $grant.scopes -or
        $grant.tools -isnot [array] -or $grant.tools.Count -gt 512 -or $config.tool_policy -isnot [pscustomobject]) { throw 'Existing read/write scopes and bounded tool policy required; no scope expansion.' }
    foreach ($list in @('scopes','tools')) {
        $seen = [Collections.Generic.HashSet[string]]::new([StringComparer]::Ordinal)
        foreach ($value in $grant.$list) { if ($value -isnot [string] -or $value.Length -lt 1 -or $value.Length -gt 256 -or -not $seen.Add($value)) { throw 'Invalid existing grant string list.' } }
    }
    foreach ($entry in $rs.grants.PSObject.Properties) {
        if ($entry.Name -cne $OwnerPrincipal -and $null -ne $entry.Value.PSObject.Properties['profile_management']) { throw 'Ambiguous owner capability mapping; explicit offline reconciliation required.' }
    }
    $actions = @('list','get','create','update','delete','set_default')
    $capability = [ordered]@{ version=1; enabled=$true; workspace_id=$WorkspaceId; device_id=$DeviceId; installation_id=$InstallationId; actions=$actions }
    $old = $grant.PSObject.Properties['profile_management']
    if ($null -ne $old) {
        $cap = $old.Value
        if ($cap -isnot [pscustomobject] -or @($cap.PSObject.Properties).Count -ne 6 -or
            ($cap.version -isnot [int] -and $cap.version -isnot [long]) -or $cap.version -ne 1 -or $cap.enabled -isnot [bool] -or
            $cap.workspace_id -isnot [string] -or $cap.workspace_id -cne $WorkspaceId -or
            $cap.device_id -isnot [string] -or $cap.device_id -cne $DeviceId -or
            $cap.installation_id -isnot [string] -or $cap.installation_id -cne $InstallationId -or
            $cap.actions -isnot [array] -or $cap.actions.Count -ne 6 -or
            (@($cap.actions | Sort-Object) -join ',') -cne (@($actions | Sort-Object) -join ',')) { throw 'Malformed/different existing capability; never silently repair authority.' }
    }
    $grantPath = @('resource_server','grants',$OwnerPrincipal)
    $text = Set-ProfileAdminMember $parsed.Text $grantPath 'profile_management' (ConvertTo-Json -InputObject $capability -Depth 8 -Compress)
    $tools = @($grant.tools)
    foreach ($action in $actions) {
        $tool = 'files_profile_admin_' + $action; $scope = 'files:write'; if ($action -cin @('list','get')) { $scope = 'files:read' }
        if ($tool -cnotin $tools) { $tools += $tool }
        $existing = $config.tool_policy.PSObject.Properties[$tool]
        if ($null -ne $existing) {
            $enabledProperty = $existing.Value.PSObject.Properties['enabled']
            if ($existing.Value -isnot [pscustomobject] -or $existing.Value.scope -isnot [string] -or $existing.Value.scope -cne $scope -or ($null -ne $enabledProperty -and ($enabledProperty.Value -isnot [bool] -or $enabledProperty.Value -ne $true))) { throw 'Conflicting/disabled existing exact tool policy; no implicit repair.' }
        } else { $text = Set-ProfileAdminMember $text @('tool_policy') $tool (ConvertTo-Json -InputObject ([ordered]@{scope=$scope;enabled=$true}) -Compress) }
    }
    if ($tools.Count -gt 512) { throw 'Expanded exact tool list exceeds consumer bound.' }
    # Preserve all existing tools and their order. No legacy admin or private catalog tool is added.
    $text = Set-ProfileAdminMember $text $grantPath 'tools' (ConvertTo-Json -InputObject @($tools) -Compress)
    $next = $utf8.GetBytes($text)
    if ($next.Length -gt 1048576) { throw 'Capability candidate exceeds consumer bound.' }
    $null = Read-StrictJson $next
    return ,$next
}

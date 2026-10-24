[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][string]$InstallRoot,
    [switch]$EnableCommands
)
# Offline owner approval, not enrollment. No scope/token issuance, grant renewal or process launch.
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'WindowsDashboard-Provisioning.ps1')
. (Join-Path $PSScriptRoot 'Owner-PrivateConfig.ps1')
Assert-ZagentOwnerConsole
$InstallRoot = (Resolve-Path -LiteralPath $InstallRoot).Path.TrimEnd('\')
Assert-ZagentPlainPath $InstallRoot
if ($InstallRoot -notmatch '\A[A-Za-z]:\\') { throw 'Local drive installation required.' }
$cores = @(Find-Core)
if ($cores.Count -ne 1 -or -not $cores[0].CommandLine) { throw 'Exactly one running Core is needed for trusted path discovery.' }
if ((Read-OneArgument $cores[0].CommandLine '--root').TrimEnd('\') -ine $InstallRoot) { throw 'Core installation mismatch.' }
$data = Read-OneArgument $cores[0].CommandLine '--data-root'
Assert-ZagentOwnerAcl $data
$profilePath = Join-Path $data 'files\config\profiles.json'
$tunnelPath = Join-Path $data 'tunnel\config\tunnel.json'
$commandPath = Join-Path $data 'files\config\remote_execution_policy.json'
$profileBytes = Read-BoundedBytes $profilePath
$tunnelBytes = Read-BoundedBytes $tunnelPath
$profiles = (Read-StrictJson $profileBytes).Object
$tunnel = (Read-StrictJson $tunnelBytes).Object
$resource = $tunnel.resource_server
$issuer = 'https://vmi3669591.contaboserver.net/realms/zagent'
$principal = 'principal_v1_41d40891edc920d08c8bf7d58f508bb1a082a9dc8dc5bb70f4fa2d913161a59d'
if ($resource.issuer -cne $issuer -or $resource.resource_uri -cne 'https://zagent.ikbalzohr.web.id/mcp' -or
    $resource.workspace_id -cne 'workspace-local' -or $resource.introspection_client_id -cne 'zagent-resource-server' -or
    $resource.introspection_endpoint -cne ($issuer + '/protocol/openid-connect/token/introspect')) { throw 'Existing trusted OAuth binding mismatch.' }
$grantProperty = $resource.grants.PSObject.Properties[$principal]
if ($null -eq $grantProperty) { throw 'Existing owner grant missing.' }
$grant = $grantProperty.Value
$binding = $grant.files_resource
if ($grant.revoked -isnot [bool] -or $grant.revoked -ne $false -or $binding.revoked -isnot [bool] -or $binding.revoked -ne $false -or
    $binding.kind -cne 'files' -or $binding.profile_id -cne 'appBridge' -or
    $binding.resource_id -cne 'workspace:workspace-local:approved-repository' -or
    $binding.device_id -cne '7338141d-ab55-4d78-a97e-35336f970fb5' -or
    $binding.installation_id -cne '7c82db6b-f6f2-4072-bd38-7ed763aa45d3') { throw 'Existing active workspace binding mismatch; no grant activation performed.' }
if ($grant.expires_at -le [DateTimeOffset]::UtcNow.ToUnixTimeSeconds()) { throw 'Grant expired; no renewal performed.' }
$approved = @($profiles.profiles | Where-Object { $_.name -ceq 'appBridge' })
$root = Join-Path $InstallRoot 'workspace'
if ($profiles.active_profile -cne 'appBridge' -or $approved.Count -ne 1 -or
    $approved[0].enabled -isnot [bool] -or $approved[0].enabled -ne $true -or
    $approved[0].authorized_by_user -isnot [bool] -or $approved[0].authorized_by_user -ne $true -or
    $approved[0].mode -cnotin @('read-only','read-write') -or
    [IO.Path]::GetFullPath($approved[0].root).TrimEnd('\') -ine $root.TrimEnd('\')) { throw 'Existing approved profile/root mismatch; no automatic root or profile adoption.' }
Assert-ZagentPlainPath $root
$catalogPath = Join-Path $PSScriptRoot '..\files-capabilities.json'
Assert-ZagentPlainPath $catalogPath
if ((Get-Item -LiteralPath $catalogPath).Length -gt 1048576) { throw 'Catalog size invalid.' }
$catalogBytes = [IO.File]::ReadAllBytes($catalogPath)
$catalog = (Read-StrictJson $catalogBytes).Object
if ($catalog.schema_version -ne 1 -or $catalog.tools -isnot [pscustomobject]) { throw 'Capability catalog contract mismatch.' }
$desiredTools = @()
$desiredScopes = @('files:read','files:write')
if ($EnableCommands) { $desiredScopes += 'files:execute' }
$blocked = @($catalog.management_only) + @($catalog.unsupported)
foreach ($entry in $catalog.tools.PSObject.Properties) {
    if ($entry.Name -cnotmatch '\Afiles_[a-z0-9_]+\z' -or $entry.Value -cnotin @('files:read','files:write','files:execute') -or $entry.Name -cin $blocked) { throw 'Invalid/blocked tool in capability catalog.' }
    if ($entry.Value -ceq 'files:execute' -and -not $EnableCommands) { continue }
    $desiredTools += $entry.Name
}
$desiredTools = @($desiredTools | Sort-Object -Unique)
if ($desiredTools.Count -lt 2 -or 'files_stat' -cnotin $desiredTools -or 'files_read' -cnotin $desiredTools) { throw 'Incomplete capability catalog.' }
# Refuse removal of previously provisioned unrelated scopes/tools; explicit review is required.
foreach ($scope in @($grant.scopes)) { if ($scope -cnotin $desiredScopes) { throw 'Unrelated existing grant scope requires review.' } }
foreach ($tool in @($grant.tools)) { if ($tool -cnotin $desiredTools) { throw 'Unrelated existing grant tool requires review.' } }
$oldPolicy = $tunnel.PSObject.Properties['tool_policy']
if ($null -eq $oldPolicy) { $tunnel | Add-Member -NotePropertyName tool_policy -NotePropertyValue ([pscustomobject]@{}) }
elseif ($oldPolicy.Value -isnot [pscustomobject]) { throw 'tool_policy must be an object.' }
foreach ($tool in $desiredTools) {
    $scope = $catalog.tools.$tool
    $existing = $tunnel.tool_policy.PSObject.Properties[$tool]
    if ($null -ne $existing) {
        $enabled = $existing.Value.PSObject.Properties['enabled']
        if ($existing.Value -isnot [pscustomobject] -or $existing.Value.scope -cne $scope -or
            ($null -ne $enabled -and ($enabled.Value -isnot [bool] -or $enabled.Value -ne $true))) { throw 'Conflicting existing tool policy; no overwrite performed.' }
    } else { $tunnel.tool_policy | Add-Member -NotePropertyName $tool -NotePropertyValue ([pscustomobject]@{ scope = $scope }) }
}
$commandBefore = $null
$commandBytes = $null
if ($EnableCommands) {
    Assert-MigrationPrivatePath ([IO.Path]::GetDirectoryName($commandPath))
    if (Test-Path -LiteralPath $commandPath) { $commandBefore = Read-BoundedBytes $commandPath; $null = Read-StrictJson $commandBefore }
    $executables = @()
    # Files' isolated interpreter only; never adopt ArcGIS Python from PATH.
    $filesPython = Join-Path $env:LOCALAPPDATA 'Zagent-Envs\files\Scripts\python.exe'
    if (Test-Path -LiteralPath $filesPython -PathType Leaf) { Assert-ZagentPlainPath $filesPython; $executables += [IO.Path]::GetFullPath($filesPython) }
    foreach ($name in @('node.exe','npm.cmd','npx.cmd','git.exe','cmd.exe')) {
        $commands = @(Get-Command $name -CommandType Application -ErrorAction SilentlyContinue)
        if ($commands.Count -gt 0) { $exe = $commands[0].Source; Assert-ZagentPlainPath $exe; $executables += [IO.Path]::GetFullPath($exe) }
    }
    # Prefer a physical executable over Microsoft Store app-execution aliases.
    # Exactly one shell is selected; reparse checks remain strict everywhere.
    $shellCandidates = @((Join-Path $PSHOME 'pwsh.exe'))
    $commands = @(Get-Command 'pwsh.exe' -CommandType Application -ErrorAction SilentlyContinue)
    foreach ($command in $commands) { $shellCandidates += $command.Source }
    $shellCandidates += Join-Path ([Environment]::SystemDirectory) 'WindowsPowerShell\v1.0\powershell.exe'
    $selectedShell = $null
    foreach ($candidate in @($shellCandidates | Select-Object -Unique)) {
        if (-not (Test-Path -LiteralPath $candidate -PathType Leaf)) { continue }
        try {
            Assert-ZagentPlainPath $candidate
        } catch {
            if ($_.Exception.Message -cne 'Reparse path/ancestor rejected.') { throw }
            Write-Host ('Skipping reparse shell candidate: ' + $candidate)
            continue
        }
        $selectedShell = [IO.Path]::GetFullPath($candidate)
        break
    }
    if (-not $selectedShell) { throw 'No regular-file PowerShell executable available; no write performed.' }
    Write-Host ('Selected command shell: ' + $selectedShell)
    $executables += $selectedShell
    $executables = @($executables | Sort-Object -Unique)
    if ($executables.Count -eq 0) { throw 'No explicitly resolved command executables available.' }
    $commandTools = @($desiredTools | Where-Object { $catalog.tools.$_ -ceq 'files:execute' })
    if ($commandTools.Count -eq 0) { throw 'Catalog has no supported command tools; commands not activated.' }
    $commandPolicy = [ordered]@{ version = 1; enabled = $true; execution_mode = 'owner-account'; acknowledge_host_access = $true;
        profile_id = 'appBridge'; root = $root; allowed_tools = $commandTools; allowed_executables = $executables;
        max_timeout_seconds = 1800; max_output_chars = 200000 }
    $commandBytes = $utf8.GetBytes((ConvertTo-Json -InputObject $commandPolicy -Depth 64))
}
Write-Host ('Approved root remains: ' + $root)
Write-Host ('Tool count selected: ' + $desiredTools.Count)
if ((Read-Host 'Type ALLOW READ WRITE to approve file changes/deletion in this existing workspace') -cne 'ALLOW READ WRITE') { throw 'Cancelled; no write performed.' }
if ($EnableCommands) {
    Write-Host 'WARNING: commands run with this Windows owner account rights, not an OS sandbox. CWD does not constrain filesystem or network access.'
    if ((Read-Host 'Type ALLOW OWNER ACCOUNT EXECUTION to approve this host-access risk') -cne 'ALLOW OWNER ACCOUNT EXECUTION') { throw 'Cancelled; no write performed.' }
}
Write-Host 'Now use Overview > Stop Core (NOT Stop all agents). Leave Core stopped until all read-backs pass.'
$null = Read-Host 'Press ENTER only after Core has exited'
Assert-CoreStopped
Assert-SnapshotUnchanged $profilePath $profileBytes
Assert-SnapshotUnchanged $tunnelPath $tunnelBytes
if ([Convert]::ToBase64String([IO.File]::ReadAllBytes($catalogPath)) -cne [Convert]::ToBase64String($catalogBytes)) { throw 'Catalog changed during approval.' }
if ($null -ne $commandBefore) { Assert-SnapshotUnchanged $commandPath $commandBefore }
elseif ($EnableCommands -and (Test-Path -LiteralPath $commandPath)) { throw 'Command policy appeared concurrently.' }
if ($grant.expires_at -le [DateTimeOffset]::UtcNow.ToUnixTimeSeconds()) { throw 'Grant expired while waiting; no renewal performed.' }
# Only this existing profile changes mode; never alter its root or other profiles.
$approved[0].mode = 'read-write'
$grant.scopes = $desiredScopes
$grant.tools = $desiredTools
$resource.scopes_supported = @(@($resource.scopes_supported) + $desiredScopes | Sort-Object -Unique)
$resource.policy_revision = 'files-capabilities-' + [guid]::NewGuid().ToString('N')
$nextProfiles = $utf8.GetBytes((ConvertTo-Json -InputObject $profiles -Depth 64))
$nextTunnel = $utf8.GetBytes((ConvertTo-Json -InputObject $tunnel -Depth 64))
$null = Read-StrictJson $nextProfiles
$null = Read-StrictJson $nextTunnel
function Write-PrivateAtomic([string]$Path, [byte[]]$Bytes, $Before) {
    Assert-CoreStopped
    Assert-MigrationPrivatePath ([IO.Path]::GetDirectoryName($Path))
    $tag = [guid]::NewGuid().ToString('N')
    $temp = $Path + '.' + $tag + '.tmp'
    $backup = $Path + '.' + $tag + '.bak'
    Assert-ZagentPlainPath $temp
    Assert-ZagentPlainPath $backup
    if ((Test-Path -LiteralPath $temp) -or (Test-Path -LiteralPath $backup)) { throw 'Private artifact collision.' }
    $stream = [IO.File]::Open($temp, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write, [IO.FileShare]::None)
    try { $stream.Write($Bytes, 0, $Bytes.Length); $stream.Flush($true) } finally { $stream.Dispose() }
    Set-ZagentOwnerAcl $temp
    if ($null -ne $Before) {
        Assert-SnapshotUnchanged $Path $Before
        [IO.File]::Replace($temp, $Path, $backup)
        Assert-MigrationPrivatePath $backup
        if ([Convert]::ToBase64String((Read-BoundedBytes $backup)) -cne [Convert]::ToBase64String($Before)) { throw 'Backup mismatch; keep Core stopped.' }
        Write-Host ('Private backup: ' + $backup)
    } else {
        if (Test-Path -LiteralPath $Path) { throw 'New target appeared concurrently.' }
        [IO.File]::Move($temp, $Path)
    }
    if ([Convert]::ToBase64String((Read-BoundedBytes $Path)) -cne [Convert]::ToBase64String($Bytes)) { throw 'Read-back mismatch; keep Core stopped.' }
}
# Resource grant is written LAST. This is not a multi-file transaction; on any error,
# keep Core stopped and preserve every backup. Never auto-start or auto-rollback.
try {
    Write-PrivateAtomic $profilePath $nextProfiles $profileBytes
    if ($EnableCommands) { Write-PrivateAtomic $commandPath $commandBytes $commandBefore }
    Assert-SnapshotUnchanged $profilePath $nextProfiles
    if ($EnableCommands) { Assert-SnapshotUnchanged $commandPath $commandBytes }
    Write-PrivateAtomic $tunnelPath $nextTunnel $tunnelBytes
    Assert-SnapshotUnchanged $profilePath $nextProfiles
    Assert-SnapshotUnchanged $tunnelPath $nextTunnel
    if ($EnableCommands) { Assert-SnapshotUnchanged $commandPath $commandBytes }
    Assert-CoreStopped
    Write-Host 'FILES_CAPABILITIES_CONFIGURED; exact backup/read-back verified; original grant expiry/revocation and workspace root preserved. Windows behavioral tests and remote canaries NOT_VERIFIED.'
    Write-Host 'Start the existing enrollment only after the reviewed Windows tests pass. OAuth scope upgrade requires a fresh consent flow; no OAuth tokens were changed here.'
} catch {
    Write-Host 'ACTIVATION_INCOMPLETE: keep Core stopped. Preserve all .bak/.tmp artifacts; do not rerun provisioning or auto-start. Inspect the local error before recovery.'
    throw
}

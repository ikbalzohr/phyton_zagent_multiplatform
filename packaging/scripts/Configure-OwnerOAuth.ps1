[CmdletBinding()]
param([Parameter(Mandatory=$true)][string]$InstallRoot)
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'WindowsDashboard-Provisioning.ps1')
Assert-ZagentOwnerConsole
$InstallRoot = (Resolve-Path -LiteralPath $InstallRoot).Path
$coreExe = Join-Path $InstallRoot 'src\Zagent.Core\bin\Debug\net10.0\Zagent.Core.exe'
function Find-Core { @(Get-CimInstance Win32_Process -Filter "Name='Zagent.Core.exe'" | Where-Object { $_.ExecutablePath -eq $coreExe }) }
$processes = @(Find-Core)
if ($processes.Count -ne 1) { throw 'One running Core for this repository is required to discover its existing DataRoot.' }
$m = [regex]::Match($processes[0].CommandLine, '(?:^|\s)--data-root\s+(?:"([^"]+)"|(\S+))')
if (-not $m.Success) { throw 'Core DataRoot argument missing.' }
$data = $m.Groups[1].Value
if (-not $data) { $data = $m.Groups[2].Value }
$data = (Resolve-Path -LiteralPath $data).Path
Assert-ZagentPlainPath $data
Assert-ZagentOwnerAcl $data
function Read-LocalJson([string]$Path) {
    Assert-ZagentPlainPath $Path
    Get-Content -LiteralPath $Path -Raw | ConvertFrom-Json
}
$dashboard = Read-LocalJson (Join-Path $data 'config\dashboard.json')
$identity = Read-LocalJson (Join-Path $data 'config\device_identity.json')
$profiles = Read-LocalJson (Join-Path $data 'files\config\profiles.json')
if ($dashboard.WorkspaceId -cne 'workspace-local' -or $identity.device_id -cne '7338141d-ab55-4d78-a97e-35336f970fb5' -or $identity.installation_id -cne '7c82db6b-f6f2-4072-bd38-7ed763aa45d3') { throw 'Owner installation metadata changed; no write performed.' }
$approved = @($profiles.profiles | Where-Object { $_.name -ceq 'appBridge' })
$expectedRoot = Join-Path $InstallRoot 'workspace'
if ($profiles.active_profile -cne 'appBridge' -or $approved.Count -ne 1 -or $approved[0].enabled -ne $true -or $approved[0].mode -cne 'read-only' -or [IO.Path]::GetFullPath($approved[0].root).TrimEnd('\') -ine $expectedRoot.TrimEnd('\')) { throw 'The reviewed read-only Files profile changed; no write performed.' }
$credential = Join-Path $data 'config\oauth-introspection.dpapi.json'
Assert-ZagentPlainPath $credential
Assert-ZagentOwnerAcl $credential
$target = Join-Path $data 'tunnel\config\tunnel.json'
Assert-ZagentPlainPath $target
Write-Host 'Discovery complete. Use Stop Core in the dashboard now. Do not delete provisioning.'
$null = Read-Host 'Press ENTER only after Core has stopped'
if (@(Find-Core).Count -ne 0) { throw 'Core is still running; no write performed.' }
# Recheck after the interactive boundary. The operation never changes Files approval.
$profilesAfter = Read-LocalJson (Join-Path $data 'files\config\profiles.json')
if (($profiles | ConvertTo-Json -Depth 64 -Compress) -cne ($profilesAfter | ConvertTo-Json -Depth 64 -Compress)) { throw 'Files approval changed while waiting; no write performed.' }
$before = [IO.File]::ReadAllBytes($target)
$config = [Text.Encoding]::UTF8.GetString($before) | ConvertFrom-Json
$existing = $config.PSObject.Properties['resource_server']
if ($null -ne $existing -and $null -ne $existing.Value -and @($existing.Value.PSObject.Properties).Count -gt 0) { throw 'Existing resource_server requires explicit review; no overwrite performed.' }
$issuer = 'https://vmi3669591.contaboserver.net/realms/zagent'
$principal = 'principal_v1_41d40891edc920d08c8bf7d58f508bb1a082a9dc8dc5bb70f4fa2d913161a59d'
$grant = [ordered]@{
    revoked = $true; expires_at = [DateTimeOffset]::UtcNow.AddHours(24).ToUnixTimeSeconds()
    scopes = @('files:read'); tools = @('files_stat','files_read')
    files_resource = [ordered]@{ resource_id = 'workspace:workspace-local:approved-repository'; kind = 'files'; profile_id = 'appBridge'; device_id = $identity.device_id; installation_id = $identity.installation_id; revoked = $true }
}
$grants = [ordered]@{}; $grants[$principal] = $grant
$resource = [ordered]@{
    resource_uri = 'https://vmi3669591.contaboserver.net/mcp'
    issuer = $issuer; authorization_servers = @($issuer)
    introspection_endpoint = $issuer + '/protocol/openid-connect/token/introspect'
    introspection_client_id = 'zagent-resource-server'
    introspection_secret_env = 'ZAGENT_OAUTH_INTROSPECTION_SECRET'
    workspace_id = 'workspace-local'; policy_revision = 'oauth-readonly-' + [guid]::NewGuid().ToString('N')
    scopes_supported = @('files:read'); grants = $grants
}
$config | Add-Member -NotePropertyName resource_server -NotePropertyValue $resource -Force
$bytes = [Text.UTF8Encoding]::new($false).GetBytes(($config | ConvertTo-Json -Depth 64))
$id = [guid]::NewGuid().ToString('N')
$temp = $target + '.' + $id + '.tmp'; $backup = $target + '.' + $id + '.bak'
Assert-ZagentPlainPath $temp
$stream = [IO.File]::Open($temp, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write, [IO.FileShare]::None)
try { $stream.Write($bytes, 0, $bytes.Length); $stream.Flush($true) } finally { $stream.Dispose() }
if ([Convert]::ToBase64String($before) -cne [Convert]::ToBase64String([IO.File]::ReadAllBytes($target))) { throw 'Concurrent configuration change; no replacement performed.' }
[IO.File]::Replace($temp, $target, $backup)
$readback = Read-LocalJson $target
if (($readback.resource_server | ConvertTo-Json -Depth 64 -Compress) -cne ($resource | ConvertTo-Json -Depth 64 -Compress)) { throw 'Read-back failed; preserve backup and stop.' }
Write-Host 'OAUTH_RESOURCE_CONFIG_WRITTEN; read-back verified; grant REVOKED; public MCP NOT_VERIFIED.'
Write-Host ('Private configuration backup: ' + $backup)
Write-Host 'Restart with Start-OwnerCore.ps1. No OAuth login, network exposure or profile changes were performed.'

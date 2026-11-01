[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][string]$InstallRoot,
    [string]$DataRoot = '',
    [string]$CoreExecutable = '',
    [string]$CertificateThumbprint = '',
    [switch]$CreateCertificate,
    [switch]$TrustCertificate,
    [Parameter(Mandatory=$true)][string]$WorkspaceId,
    [string]$DashboardUrl = 'https://localhost:19443/',
    [switch]$Development,
    [switch]$RegisterStartup
)
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'WindowsDashboard-Provisioning.ps1')
Assert-ZagentOwnerConsole
$InstallRoot = (Resolve-Path -LiteralPath $InstallRoot).Path
Assert-ZagentPlainPath $InstallRoot
if (-not $DataRoot) { $DataRoot = if ($Development) { Join-Path $InstallRoot 'dev\data' } else { Join-Path $InstallRoot 'data' } }
$DataRoot = [IO.Path]::GetFullPath($DataRoot)
Assert-ZagentPlainPath $DataRoot
if ($DataRoot.TrimEnd('\') -eq $InstallRoot.TrimEnd('\') -or $DataRoot -eq [IO.Path]::GetPathRoot($DataRoot)) { throw 'Choose a dedicated DataRoot, not the install root or drive root.' }
Assert-ZagentDashboardOrigin $DashboardUrl
if ($WorkspaceId -cnotmatch '^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$') { throw 'Valid workspace identifier required.' }
if ($CreateCertificate -eq [bool]$CertificateThumbprint) { throw 'Choose exactly one: -CreateCertificate or -CertificateThumbprint.' }
if ($TrustCertificate -and -not $CreateCertificate) { throw 'Automatic trust is restricted to the new localhost self-signed certificate; manage existing CA trust separately.' }
if (-not $CoreExecutable) {
    if ($Development) { throw 'Development requires explicit -CoreExecutable path to the Windows-built Core apphost.' }
    $CoreExecutable = Join-Path $InstallRoot 'Zagent.Core.exe'
}
$CoreExecutable = (Resolve-Path -LiteralPath $CoreExecutable).Path
Assert-ZagentPlainPath $CoreExecutable
if (-not (Test-Path -LiteralPath $CoreExecutable -PathType Leaf) -or [IO.Path]::GetFileName($CoreExecutable) -ine 'Zagent.Core.exe') { throw 'Zagent.Core.exe Windows apphost required; no build/install is performed.' }
if (-not $Development) {
    $manifest = Get-Content -LiteralPath (Join-Path $InstallRoot 'payload-manifest.json') -Raw | ConvertFrom-Json
    if ($manifest.product_line -ne 'zagent-mcp-v1' -or $manifest.suite_version -ne '1.0.0') { throw 'Provision only the v1 installed payload.' }
}
$configDirectory = Join-Path $DataRoot 'config'
$config = Join-Path $configDirectory 'dashboard.json'
$secretPath = Join-Path $configDirectory 'internal-secrets.dpapi.json'
foreach ($path in @($config,$secretPath)) {
    Assert-ZagentPlainPath $path
    if (Test-Path -LiteralPath $path) { throw 'Provisioning already exists or is partial; offline owner recovery required. No overwrite.' }
}
if ($RegisterStartup) {
    if ($Development) { throw 'DEV startup registration is deliberately unsupported; launch explicitly.' }
    $startup = [Environment]::GetFolderPath('Startup')
    $shortcut = Join-Path $startup ('Zagent Core1-'+(Split-Path $InstallRoot -Leaf)+'.lnk')
    Assert-ZagentPlainPath $shortcut
    if (Test-Path -LiteralPath $shortcut) { throw 'Startup entry already exists; no overwrite.' }
}
# Refuse to recursively adopt existing data. A fresh or already private root is required.
if (Test-Path -LiteralPath $DataRoot) { Assert-ZagentOwnerAcl $DataRoot }
$keyDirectory = Join-Path $DataRoot 'dashboard-keys'
foreach ($directory in @($DataRoot,$configDirectory,$keyDirectory)) { New-ZagentPrivateDirectory $directory }
if (@(Get-ChildItem -LiteralPath $keyDirectory -Force).Count -ne 0) { throw 'Existing dashboard keys require explicit offline recovery; fresh enrollment will not adopt them.' }
if ($CreateCertificate) {
    $certificate = New-SelfSignedCertificate -DnsName 'localhost' -Subject 'CN=localhost' -CertStoreLocation 'Cert:\CurrentUser\My' -FriendlyName 'Zagent local dashboard (owner only)' -Type SSLServerAuthentication -KeyAlgorithm RSA -KeyLength 3072 -HashAlgorithm SHA256 -KeyExportPolicy NonExportable -NotAfter (Get-Date).AddYears(1)
    $CertificateThumbprint = $certificate.Thumbprint
}
if ($CertificateThumbprint -cnotmatch '^[0-9A-Fa-f]{40}$') { throw 'Exact SHA1 certificate-store thumbprint required, no path or whitespace.' }
$certificate = Get-Item -LiteralPath ('Cert:\CurrentUser\My\'+$CertificateThumbprint)
Assert-ZagentLocalCertificate $certificate
if ($TrustCertificate) {
    $store = [Security.Cryptography.X509Certificates.X509Store]::new('Root','CurrentUser')
    $store.Open([Security.Cryptography.X509Certificates.OpenFlags]::ReadWrite)
    try {
        # Trust only the public certificate; never export/persist a private key or PFX password.
        $public = [Security.Cryptography.X509Certificates.X509Certificate2]::new($certificate.RawData)
        try { $store.Add($public) } finally { $public.Dispose() }
        if (@($store.Certificates.Find([Security.Cryptography.X509Certificates.X509FindType]::FindByThumbprint,$CertificateThumbprint,$false)).Count -ne 1) { throw 'CurrentUser trust read-back failed.' }
    } finally { $store.Dispose() }
}
New-ZagentInternalSecrets $secretPath
# Core binds Dashboard access to the interactive Windows owner. No username,
# password, bearer token or browser credential is created for the local UI.
& $CoreExecutable --provision-dashboard --root $InstallRoot --data-root $DataRoot --dashboard-config $config --dashboard-url $DashboardUrl --certificate-thumbprint $CertificateThumbprint --workspace-id $WorkspaceId
if ($LASTEXITCODE -ne 0) { throw 'Core dashboard provisioning failed; partial state retained for explicit offline recovery, no startup registered.' }
Set-ZagentOwnerAcl $config
$stored = Get-Content -LiteralPath $config -Raw | ConvertFrom-Json
if ($stored.Url -cne $DashboardUrl -or $stored.CertificateThumbprint -ine $CertificateThumbprint -or $stored.WorkspaceId -cne $WorkspaceId -or -not $stored.Administrator -or $stored.PasswordHash -ne '' -or -not $stored.SecurityStamp -or $stored.RemoteEnabled -ne $false) { throw 'Provisioned config read-back mismatch.' }
Assert-ZagentOwnerAcl $secretPath
if ($RegisterStartup) {
    $shell = New-Object -ComObject WScript.Shell
    $link = $shell.CreateShortcut($shortcut)
    $link.TargetPath = $CoreExecutable
    $link.Arguments = '--dashboard --root "'+$InstallRoot+'" --data-root "'+$DataRoot+'" --dashboard-config "'+$config+'"'
    $link.WorkingDirectory = $InstallRoot
    $link.Description = 'Zagent per-user interactive local dashboard (not a Session0 service)'
    $link.Save()
    $check = $shell.CreateShortcut($shortcut)
    if ($check.TargetPath -ne $CoreExecutable -or $check.Arguments -cne $link.Arguments) { throw 'Startup shortcut read-back failed.' }
}
Write-Output ('Local provisioning saved. Origin: '+$DashboardUrl+' Certificate: '+$CertificateThumbprint)
Write-Output 'Local-owner Dashboard uses no browser login. HTTPS certificate, Windows owner, Origin and CSRF checks remain mandatory. MCP OAuth/remote stays independently gated.'

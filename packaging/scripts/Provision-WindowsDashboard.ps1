param(
    [Parameter(Mandatory=$true)][string]$InstallRoot,
    [string]$DataRoot = '',
    [Parameter(Mandatory=$true)][string]$CertificateThumbprint,
    [Parameter(Mandatory=$true)][string]$WorkspaceId,
    [Parameter(Mandatory=$true)][string]$Account,
    [string]$DashboardUrl = 'https://127.0.0.1:19443/',
    [switch]$RegisterStartup
)
$ErrorActionPreference = 'Stop'
if ($env:OS -ne 'Windows_NT' -or -not [Environment]::UserInteractive -or [Console]::IsInputRedirected) { throw 'Run only in the interactive Windows installation-owner console.' }
$InstallRoot = (Resolve-Path $InstallRoot).Path
if (-not $DataRoot) { $DataRoot = Join-Path $InstallRoot 'data' }
$DataRoot = [IO.Path]::GetFullPath($DataRoot)
$core = Join-Path $InstallRoot 'Zagent.Core.exe'
if (-not (Test-Path $core -PathType Leaf)) { throw 'Installed Core executable missing.' }
$manifest = Get-Content (Join-Path $InstallRoot 'payload-manifest.json') -Raw | ConvertFrom-Json
if ($manifest.product_line -ne 'zagent-mcp-v1' -or $manifest.suite_version -ne '1.0.0') { throw 'Provision only the v1 installed payload.' }
$uri = [Uri]$DashboardUrl
if ($uri.Scheme -ne 'https' -or -not $uri.IsLoopback -or $uri.AbsolutePath -ne '/' -or $uri.Query -or $uri.Fragment -or $uri.UserInfo) { throw 'Exact HTTPS loopback origin required.' }
$certificate = Get-Item -LiteralPath ("Cert:\CurrentUser\My\"+$CertificateThumbprint)
if (-not $certificate.HasPrivateKey -or $certificate.NotAfter -le (Get-Date) -or $certificate.NotBefore -gt (Get-Date)) { throw 'Valid CurrentUser TLS certificate/private key required; certificate issuance and trust are external prerequisites.' }
$owner = [Security.Principal.WindowsIdentity]::GetCurrent().User
foreach ($directory in @($DataRoot,(Join-Path $DataRoot 'config'),(Join-Path $DataRoot 'dashboard-keys'))) {
    $ancestor = [IO.DirectoryInfo]::new([IO.Path]::GetFullPath($directory))
    while ($null -ne $ancestor) {
        if ($ancestor.Exists -and ($ancestor.Attributes -band [IO.FileAttributes]::ReparsePoint)) { throw 'Data/config path must not traverse reparse points.' }
        $ancestor = $ancestor.Parent
    }
    if (Test-Path $directory) {
        if ((Get-Item -LiteralPath $directory -Force).Attributes -band [IO.FileAttributes]::ReparsePoint) { throw "Reparse directory rejected: $directory" }
    } else { New-Item -ItemType Directory -Path $directory | Out-Null }
    $acl = [Security.AccessControl.DirectorySecurity]::new()
    $acl.SetOwner($owner)
    $acl.SetAccessRuleProtection($true,$false)
    $rule = [Security.AccessControl.FileSystemAccessRule]::new($owner,'FullControl','ContainerInherit,ObjectInherit','None','Allow')
    $acl.AddAccessRule($rule)
    Set-Acl -LiteralPath $directory -AclObject $acl
    $actual = Get-Acl -LiteralPath $directory
    if (-not $actual.AreAccessRulesProtected) { throw "ACL protection not applied: $directory" }
}
$config = Join-Path $DataRoot 'config\dashboard.json'
if (Test-Path $config) { throw 'Account already exists. Use documented offline recovery; no silent overwrite.' }
# Password is read without echo by Core; never accepted as a script/command-line parameter.
& $core --provision-dashboard --dashboard-config $config --dashboard-url $DashboardUrl --certificate-thumbprint $CertificateThumbprint --workspace-id $WorkspaceId --account $Account
if ($LASTEXITCODE -ne 0) { throw 'Core dashboard provisioning failed.' }
$stored = Get-Content -LiteralPath $config -Raw | ConvertFrom-Json
if ($stored.Url -ne $DashboardUrl -or $stored.WorkspaceId -ne $WorkspaceId -or $stored.Administrator -ne $Account -or -not $stored.PasswordHash -or $stored.RemoteEnabled) { throw 'Provisioned config read-back mismatch.' }
if ($RegisterStartup) {
    $startup = [Environment]::GetFolderPath('Startup')
    $shortcut = Join-Path $startup ('Zagent Core1-'+(Split-Path $InstallRoot -Leaf)+'.lnk')
    if (Test-Path $shortcut) { throw "Startup entry already exists: $shortcut" }
    $shell = New-Object -ComObject WScript.Shell
    $link = $shell.CreateShortcut($shortcut)
    $link.TargetPath = $core
    $link.Arguments = '--serve-dashboard --root "'+$InstallRoot+'" --data-root "'+$DataRoot+'" --dashboard-config "'+$config+'"'
    $link.WorkingDirectory = $InstallRoot
    $link.Description = 'Zagent Core1 per-user interactive dashboard host (not a Session0 service)'
    $link.Save()
    $check = $shell.CreateShortcut($shortcut)
    if ($check.TargetPath -ne $core -or $check.Arguments -ne $link.Arguments) { throw 'Startup shortcut read-back failed.' }
}
Write-Output 'Dashboard provisioning saved. Start Core and verify certificate trust, login and CSRF/Origin controls locally; this is not live acceptance.'

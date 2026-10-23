# Windows PowerShell 5.1+ helpers. Dot-source only; no product launch or global env writes.
Set-StrictMode -Version Latest
function Assert-ZagentOwnerConsole {
    if ($env:OS -ne 'Windows_NT' -or -not [Environment]::UserInteractive -or [Console]::IsInputRedirected) {
        throw 'Run in the interactive Windows installation-owner console, not a service or redirected shell.'
    }
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    if ($identity.IsSystem -or $identity.IsAnonymous) { throw 'A real interactive owner SID is required.' }
}
function Assert-ZagentPlainPath([string]$Path) {
    $item = [IO.DirectoryInfo]::new([IO.Path]::GetFullPath($Path))
    while ($null -ne $item) {
        if (Test-Path -LiteralPath $item.FullName) {
            $existing = Get-Item -LiteralPath $item.FullName -Force
            if ($existing.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Reparse path/ancestor rejected.' }
        }
        $item = $item.Parent
    }
}
function Assert-ZagentOwnerAcl([string]$Path) {
    Assert-ZagentPlainPath $Path
    $sid = [Security.Principal.WindowsIdentity]::GetCurrent().User
    $acl = Get-Acl -LiteralPath $Path
    if ($acl.GetOwner([Security.Principal.SecurityIdentifier]).Value -ne $sid.Value -or -not $acl.AreAccessRulesProtected) { throw 'Owner/protected ACL mismatch.' }
    $rules = @($acl.GetAccessRules($true,$true,[Security.Principal.SecurityIdentifier]))
    if ($rules.Count -ne 1 -or $rules[0].IdentityReference.Value -ne $sid.Value -or
        $rules[0].AccessControlType -ne [Security.AccessControl.AccessControlType]::Allow -or
        $rules[0].FileSystemRights -ne [Security.AccessControl.FileSystemRights]::FullControl -or $rules[0].IsInherited -or
        $rules[0].PropagationFlags -ne [Security.AccessControl.PropagationFlags]::None) { throw 'Owner-only FullControl DACL required.' }
    if ((Get-Item -LiteralPath $Path -Force).PSIsContainer -and
        $rules[0].InheritanceFlags -ne ([Security.AccessControl.InheritanceFlags]::ContainerInherit -bor [Security.AccessControl.InheritanceFlags]::ObjectInherit)) { throw 'Directory ACL inheritance mismatch.' }
}
function Set-ZagentOwnerAcl([string]$Path) {
    Assert-ZagentPlainPath $Path
    $sid = [Security.Principal.WindowsIdentity]::GetCurrent().User
    $existing = Get-Acl -LiteralPath $Path
    if ($existing.GetOwner([Security.Principal.SecurityIdentifier]).Value -ne $sid.Value) { throw 'Refusing to adopt another owner object.' }
    $isDirectory = (Get-Item -LiteralPath $Path -Force).PSIsContainer
    if ($isDirectory) {
        $acl = [Security.AccessControl.DirectorySecurity]::new()
        $rule = [Security.AccessControl.FileSystemAccessRule]::new($sid,'FullControl','ContainerInherit,ObjectInherit','None','Allow')
    } else {
        $acl = [Security.AccessControl.FileSecurity]::new()
        $rule = [Security.AccessControl.FileSystemAccessRule]::new($sid,'FullControl','Allow')
    }
    $acl.SetOwner($sid); $acl.SetAccessRuleProtection($true,$false); $acl.AddAccessRule($rule)
    Set-Acl -LiteralPath $Path -AclObject $acl
    Assert-ZagentOwnerAcl $Path
}
function New-ZagentPrivateDirectory([string]$Path) {
    Assert-ZagentPlainPath $Path
    if (Test-Path -LiteralPath $Path) {
        if (-not (Test-Path -LiteralPath $Path -PathType Container)) { throw 'Expected directory.' }
        Assert-ZagentOwnerAcl $Path
    } else {
        [IO.Directory]::CreateDirectory($Path) | Out-Null
        Set-ZagentOwnerAcl $Path
    }
}
function Assert-ZagentDashboardOrigin([string]$Url) {
    $uri = [Uri]$Url
    if (-not $uri.IsAbsoluteUri -or $uri.Scheme -cne 'https' -or $uri.DnsSafeHost -cne 'localhost' -or
        $uri.AbsolutePath -ne '/' -or $uri.Query -or $uri.Fragment -or $uri.UserInfo -or $uri.Port -lt 1 -or
        $Url -cne ('https://localhost:'+$uri.Port+'/')) { throw 'Exact origin https://localhost:<port>/ required; no public bind or alternate hostname.' }
}
function Assert-ZagentLocalCertificate($Certificate) {
    if (-not $Certificate.HasPrivateKey -or $Certificate.NotAfter -le (Get-Date) -or $Certificate.NotBefore -gt (Get-Date)) { throw 'Valid CurrentUser TLS private key required.' }
    $san = @($Certificate.Extensions | Where-Object { $_.Oid.Value -eq '2.5.29.17' })
    # DER SEQUENCE containing only dNSName localhost: no wildcard, IP SAN or second name.
    if ($san.Count -ne 1 -or [BitConverter]::ToString($san[0].RawData) -cne '30-0B-82-09-6C-6F-63-61-6C-68-6F-73-74') { throw 'Certificate SAN must contain exact DNS localhost only.' }
    $eku = @($Certificate.EnhancedKeyUsageList | ForEach-Object { $_.ObjectId.Value })
    if ($eku -notcontains '1.3.6.1.5.5.7.3.1') { throw 'TLS serverAuth EKU required.' }
}
function New-ZagentInternalSecrets([string]$Path) {
    Assert-ZagentPlainPath $Path
    Assert-ZagentOwnerAcl ([IO.Path]::GetDirectoryName($Path))
    if (Test-Path -LiteralPath $Path) { throw 'Internal credentials already exist; offline recovery only, never overwrite.' }
    Add-Type -AssemblyName System.Security
    $rng = [Security.Cryptography.RandomNumberGenerator]::Create()
    $one = New-Object byte[] 32; $two = New-Object byte[] 32
    $plain = $null; $decoded = $null
    try {
        $rng.GetBytes($one); $rng.GetBytes($two)
        $payload = @{ internal_token = ([BitConverter]::ToString($one).Replace('-','').ToLowerInvariant()); internal_context_key = ([BitConverter]::ToString($two).Replace('-','').ToLowerInvariant()) }
        $plain = [Text.Encoding]::UTF8.GetBytes(($payload | ConvertTo-Json -Compress))
        $cipher = [Security.Cryptography.ProtectedData]::Protect($plain,$null,[Security.Cryptography.DataProtectionScope]::CurrentUser)
        $envelope = @{ version = 1; scope = 'CurrentUser'; protected_payload = [Convert]::ToBase64String($cipher) } | ConvertTo-Json -Compress
        $stream = [IO.File]::Open($Path,[IO.FileMode]::CreateNew,[IO.FileAccess]::Write,[IO.FileShare]::None)
        try { $bytes = [Text.Encoding]::UTF8.GetBytes($envelope); $stream.Write($bytes,0,$bytes.Length); $stream.Flush($true) } finally { $stream.Dispose() }
        Set-ZagentOwnerAcl $Path
        $stored = Get-Content -LiteralPath $Path -Raw | ConvertFrom-Json
        if ($stored.version -ne 1 -or $stored.scope -cne 'CurrentUser' -or @($stored.PSObject.Properties).Count -ne 3) { throw 'Internal envelope read-back mismatch.' }
        $decoded = [Security.Cryptography.ProtectedData]::Unprotect([Convert]::FromBase64String($stored.protected_payload),$null,[Security.Cryptography.DataProtectionScope]::CurrentUser)
        if ([Convert]::ToBase64String($decoded) -cne [Convert]::ToBase64String($plain)) { throw 'DPAPI read-back mismatch.' }
    } finally {
        $rng.Dispose(); [Array]::Clear($one,0,$one.Length); [Array]::Clear($two,0,$two.Length)
        if ($null -ne $plain) { [Array]::Clear($plain,0,$plain.Length) }
        if ($null -ne $decoded) { [Array]::Clear($decoded,0,$decoded.Length) }
        $payload = $null; $envelope = $null
    }
    # Managed JSON/hex strings cannot be reliably zeroed. They never leave process memory.
}

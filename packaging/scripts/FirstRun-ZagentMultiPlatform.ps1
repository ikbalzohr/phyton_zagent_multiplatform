[CmdletBinding()]
param()
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$config = Join-Path $root 'data\config\dashboard.json'
if (Test-Path -LiteralPath $config) {
    Write-Output 'Dashboard already provisioned; no changes performed.'
    return
}
if (-not [Environment]::UserInteractive -or [Console]::IsInputRedirected) {
    throw 'First run requires an interactive Windows owner console.'
}
$provision = Join-Path $root 'setup\Provision-WindowsDashboard.ps1'
if (-not (Test-Path -LiteralPath $provision -PathType Leaf)) {
    throw 'Missing first-run provisioning helper. No credentials created.'
}
Write-Host 'Zagent Multi Platform — first-time local HTTPS configuration' -ForegroundColor Cyan
Write-Host 'No Dashboard username or password is required. Login is Windows-owner-local only.'
Write-Host 'A new, localhost-only certificate will be created and trusted for your Windows user.'
Write-Host 'This changes your CurrentUser certificate trust store, NOT machine-wide trust.'
$consent = (Read-Host 'Type YES to approve this one-time localhost certificate trust').Trim()
if ($consent -cne 'YES') {
    throw 'Certificate trust not approved; no provisioning performed.'
}
$params = @{
    InstallRoot = $root
    DataRoot = (Join-Path $root 'data')
    WorkspaceId = 'zagent-mp-test'
    DashboardUrl = 'https://localhost:19444/'
    CreateCertificate = $true
    TrustCertificate = $true
}
& $provision @params
if (-not (Test-Path -LiteralPath $config -PathType Leaf)) {
    throw 'Local-owner Dashboard configuration missing after provisioning.'
}
Write-Host 'One-time HTTPS provisioning complete. Chrome will open the Dashboard.' -ForegroundColor Green
$arcMapInstaller = Join-Path $root 'setup\Install-ArcMapIntegration.ps1'
if (Test-Path -LiteralPath $arcMapInstaller -PathType Leaf) {
    try {
        & $arcMapInstaller -InstallRoot $root -RetireProduction | Out-Host
        Write-Host 'ArcMap Multi Platform Add-In prepared for automatic startup.' -ForegroundColor Green
    }
    catch {
        Write-Warning ('ArcMap integration deferred (ArcMap may still be running): ' + $_.Exception.Message)
    }
}

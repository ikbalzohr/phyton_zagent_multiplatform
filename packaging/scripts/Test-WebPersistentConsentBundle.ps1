param([string]$Root="")
$ErrorActionPreference="Stop"
if([string]::IsNullOrWhiteSpace($Root)){$Root=(Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path}
$web=Join-Path $Root "agents\web\engine"
function Assert-Source([string]$Relative,[string[]]$Required){
 $p=Join-Path $Root $Relative
 if(-not(Test-Path -LiteralPath $p)){throw "CHROME_BUNDLE_GUARD_MISSING $Relative"}
 $s=[IO.File]::ReadAllText($p)
 foreach($phrase in $Required){if($s.IndexOf($phrase,[StringComparison]::Ordinal) -lt 0){throw "CHROME_BUNDLE_GUARD_MISSING_TOKEN $Relative $phrase"}}
 Write-Output "WEB_GUARD_PASS $Relative"
}
Assert-Source "agents\web\engine\src\bridge\Bridge.ts" @("persistentConsent","approvedTargetIds","persistentLease","consent-upgrade","targets-sync","persistent-all-tabs-v1")
Assert-Source "agents\web\engine\dist\bridge\Bridge.js" @("persistentConsent","approvedTargetIds","persistentLease","consent-upgrade","targets-sync","persistent-all-tabs-v1")
Assert-Source "agents\web\engine\dist\tools\bridge.js" @("approved_persistent","fresh-extension-heartbeat","Persistent authorization was not established")
Assert-Source "agents\web\engine\extension\background.js" @("persistent-all-tabs-v1","targets-sync","consent-upgrade","chrome.tabs.onCreated","chrome.windows.onCreated")
Assert-Source "agents\web\engine\extension\popup.js" @('act("approve")','act("disconnect")','lease?.persistent')
Assert-Source "src\Zagent.Core\Manager\ManagerIntegrationService.cs" @('"chrome.request_access"','"chrome.disconnect"')
# The UI gate follows the shipping Core dashboard, not the retired WPF screen.
$dashboard = Join-Path $Root 'src\Zagent.Core\Dashboard\DashboardHost.cs'
if (-not (Test-Path $dashboard)) { throw 'CHROME_BUNDLE_GUARD_MISSING dashboard host' }
# Functional web consent wiring remains a mandatory Windows browser acceptance gate.
Assert-Source "src\Zagent.Core\Dashboard\DashboardHost.cs" @('MapManagement','chrome.request_access','chrome.disconnect')
$popup=[IO.File]::ReadAllText((Join-Path $web "extension\popup.html"))
$buttons=[regex]::Matches($popup,"<button\b[^>]*id\s*=\s*['""]([^'""]+)['""]", "IgnoreCase")
$ids=@($buttons|ForEach-Object{$_.Groups[1].Value})
if($ids.Count -ne 2 -or $ids[0] -ne "approve" -or $ids[1] -ne "disconnect"){throw "CHROME_BUNDLE_GUARD_BUTTONS: $($ids -join ',')"}
$ext=(Join-Path $web "extension")
$built=(Join-Path $web "artifacts\chrome-bridge")
foreach($filename in @("popup.html","popup.js","popup.css","background.js")){
 $a=Get-FileHash (Join-Path $ext $filename) -Algorithm SHA256
 $b=Get-FileHash (Join-Path $built $filename) -Algorithm SHA256
 if($a.Hash -ne $b.Hash){throw "CHROME_BUNDLE_GUARD_STALE_ARTIFACT $filename"}
}
if($popup -match "id\s*=\s*['""](pair|authorize)['""]"){throw "CHROME_BUNDLE_GUARD_LEGACY_BUTTON"}
Write-Output "CHROME_BUNDLE_PERSISTENT_CONSENT_GUARD_PASS"

param([string]$Root = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path)
$ErrorActionPreference = 'Stop'
if ($env:OS -ne 'Windows_NT') { throw 'Run release checks only on the authorized local Windows machine.' }
function Assert-Release([bool]$Condition, [string]$Message) { if (-not $Condition) { throw $Message } }
$release = Get-Content (Join-Path $Root 'component-manifest.json') -Raw | ConvertFrom-Json
Assert-Release ($release.suite_version -eq '1.0.0') 'Suite version must be 1.0.0.'
foreach ($name in @('core','ui','tunnel','files','web','arcmap')) {
    Assert-Release ($release.components.$name.canonical_version -eq '1.0.0') "Product version mismatch: $name"
}
foreach ($name in @('tunnel','files','web','arcmap')) {
    $component = Get-Content (Join-Path $Root "agents\$name\$name.component.json") -Raw | ConvertFrom-Json
    Assert-Release ($component.version -eq '1.0.0') "Owner integration pending: $name manifest version"
}
$payloadScript = Get-Content (Join-Path $PSScriptRoot 'Build-ProductionPayload.ps1') -Raw
Assert-Release (-not $payloadScript.Contains('Zagent.Manager.exe')) 'WPF Manager must not ship in payload.'
$launcher = Get-Content (Join-Path $Root 'src\Zagent.Bundle\MainWindow.xaml.cs') -Raw
Assert-Release ($launcher.Contains('"--dashboard"')) 'Installer must launch the Core dashboard.'
$registration = Get-Content (Join-Path $Root 'src\Zagent.Setup\WindowsInstallationIntegration.cs') -Raw
Assert-Release ($registration.Contains('"--dashboard"')) 'Shortcuts must launch the Core dashboard.'
$solution = [xml](Get-Content (Join-Path $Root 'Zagent.slnx') -Raw)
$declared = @($solution.Solution.Folder.Project | ForEach-Object { $_.Path.Replace('\','/') })
foreach ($project in Get-ChildItem (Join-Path $Root 'src'),(Join-Path $Root 'tests') -Filter *.csproj -Recurse) {
    $relative = $project.FullName.Substring($Root.Length).TrimStart([char[]]'\/').Replace('\','/')
    # Legacy Manager reference source is not a shipping project.
    if ($relative -eq 'src/Zagent.Manager/Zagent.Manager.csproj') { continue }
    Assert-Release ($declared -contains $relative) "Solution omits project: $relative"
}
Write-Output 'RELEASE_SOURCE_PASS (source contracts only; not installer/live acceptance)'

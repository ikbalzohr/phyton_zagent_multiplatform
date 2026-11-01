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
Assert-Release (-not $payloadScript.Contains('Zagent.Manager.exe')) 'Retired desktop Manager must not ship in payload.'
Assert-Release (-not (Test-Path (Join-Path $Root 'src\Zagent.Manager'))) 'Retired WPF Manager source must be absent.'
$launcher = Get-Content (Join-Path $Root 'src\Zagent.Bundle\MainWindow.xaml.cs') -Raw
Assert-Release ($launcher.Contains('Zagent.Launcher.exe')) 'Installer must launch the installation-local Launcher.'
$registration = Get-Content (Join-Path $Root 'src\Zagent.Setup\WindowsInstallationIntegration.cs') -Raw
Assert-Release ($registration.Contains('Zagent.Launcher.exe')) 'Windows shortcuts must point to the installation-local Launcher.'
Assert-Release ($payloadScript.Contains('Zagent.Launcher.exe')) 'MCP-first payload must contain Launcher.'
Assert-Release (Test-Path (Join-Path $PSScriptRoot 'Publish-Launcher.ps1')) 'Independent Launcher publish script missing.'
$solution = [xml](Get-Content (Join-Path $Root 'Zagent.slnx') -Raw)
$declared = @($solution.Solution.Folder.Project | ForEach-Object { $_.Path.Replace('\','/') })
foreach ($relative in $declared) {
    Assert-Release ($relative -ne 'src/Zagent.Manager/Zagent.Manager.csproj') 'Retired WPF project is included in solution.'
    Assert-Release (Test-Path (Join-Path $Root $relative)) "Solution references missing project: $relative"
}
foreach ($essential in @('src/Zagent.Core/Zagent.Core.csproj','src/Zagent.Launcher/Zagent.Launcher.csproj','tests/Zagent.LauncherTests/Zagent.LauncherTests.csproj','src/Zagent.Bundle/Zagent.Bundle.csproj','src/Zagent.Setup/Zagent.Setup.csproj','src/Zagent.Shared/Zagent.Shared.csproj','tests/Zagent.ManagerFeatureTests/Zagent.ManagerFeatureTests.csproj','tests/Zagent.ManagerTests/Zagent.ManagerTests.csproj')) {
    Assert-Release ($declared -contains $essential) "Essential product/test project omitted from solution: $essential"
}
foreach ($project in Get-ChildItem (Join-Path $Root 'src'),(Join-Path $Root 'tests') -Filter *.csproj -Recurse) {
    $relative = $project.FullName.Substring($Root.Length).TrimStart([char[]]'\/').Replace('\','/')
    $content = (Get-Content -LiteralPath $project.FullName -Raw).Replace('/','\')
    Assert-Release (-not $content.Contains('src\Zagent.Manager\Zagent.Manager.csproj') -and -not $content.Contains('..\..\src\Zagent.Manager\Zagent.Manager.csproj')) "Obsolete WPF dependency in: $relative"
}
Write-Output 'RELEASE_SOURCE_PASS (source contracts only; not installer/live acceptance)'

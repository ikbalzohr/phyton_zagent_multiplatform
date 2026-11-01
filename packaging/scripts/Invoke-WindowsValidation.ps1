param(
    [string]$Dotnet = 'dotnet',
    [ValidateSet('Debug','Release')][string]$Configuration = 'Release',
    [Parameter(Mandatory=$true)][string]$EvidenceRoot,
    [string[]]$HarnessTests = @('Zagent.SetupTests','Zagent.ArchitectureTests','Zagent.SupervisorTests','Zagent.ArcMapWorkflowUnitTests','Zagent.DashboardTests','Zagent.LauncherTests'),
    [switch]$RunHarnesses
)
$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
. (Join-Path $PSScriptRoot 'Build-Common.ps1')
$sdk = Initialize-ZagentBuild -Root $root -Dotnet $Dotnet
$evidence = [IO.Path]::GetFullPath($EvidenceRoot).TrimEnd('\')
$source = [IO.Path]::GetFullPath($root).TrimEnd('\')
if ($evidence.Equals($source,[StringComparison]::OrdinalIgnoreCase) -or $evidence.StartsWith($source+'\',[StringComparison]::OrdinalIgnoreCase) -or $source.StartsWith($evidence+'\',[StringComparison]::OrdinalIgnoreCase)) {
    throw 'EvidenceRoot must be a fresh disposable sibling/outside source, never a source ancestor.'
}
if (Test-Path $evidence) { throw "EvidenceRoot must not exist: $evidence" }
New-Item -ItemType Directory -Path $evidence | Out-Null
$results = [Collections.Generic.List[object]]::new()
$env:ZAGENT_DEV_ROOT = Join-Path $evidence 'fixture'
New-Item -ItemType Directory -Path $env:ZAGENT_DEV_ROOT | Out-Null
function Invoke-Recorded([string]$Name,[string[]]$CommandArgs) {
    $started = [DateTimeOffset]::UtcNow
    & $sdk @CommandArgs *> (Join-Path $evidence ($Name+'.log'))
    $code = $LASTEXITCODE
    $results.Add([pscustomobject]@{ name=$Name; executable=$sdk; arguments=$CommandArgs; cwd=$root; exit_code=$code; started_at_utc=$started.ToString('o'); elapsed_ms=([DateTimeOffset]::UtcNow-$started).TotalMilliseconds })
    if ($code -ne 0) { throw "$Name failed ($code); inspect local evidence." }
}
Push-Location $root
try {
    & (Join-Path $PSScriptRoot 'Test-ReleaseSource.ps1') -Root $root *> (Join-Path $evidence 'release-source.log')
    $projects = @(Get-ChildItem (Join-Path $root 'src'),(Join-Path $root 'tests') -Filter *.csproj -Recurse | Sort-Object FullName)
    $projects.FullName | ConvertTo-Json | Set-Content (Join-Path $evidence 'project-inventory.json')
    # Build TestChild before any console harness. dotnet test does NOT run these Exe projects.
    Invoke-Recorded 'build-TestChild' @('build',(Join-Path $root 'tests\Zagent.TestChild\Zagent.TestChild.csproj'),'-c',$Configuration,'--nologo')
    foreach ($project in $projects) {
        Invoke-Recorded ('build-'+$project.BaseName) @('build',$project.FullName,'-c',$Configuration,'--nologo')
    }
    if ($RunHarnesses) {
        foreach ($test in $HarnessTests) {
            if ($test -notmatch '^Zagent\.[A-Za-z]+Tests$') { throw "Invalid harness name: $test" }
            $project = Join-Path $root "tests\$test\$test.csproj"
            if (-not (Test-Path $project)) { throw "Missing harness: $test" }
            $args = @('run','--project',$project,'-c',$Configuration,'--no-build')
            if ($test -eq 'Zagent.LauncherTests') { $args += @('--',$sdk) }
            Invoke-Recorded ('run-'+$test) $args
            $log = Get-Content (Join-Path $evidence ('run-'+$test+'.log')) -Raw
            if ($log -match '(?im)\b(SKIP|SKIPPED|BLOCKED)\b') { throw "Unexpected skipped/blocked coverage: $test" }
        }
    }
} finally {
    [pscustomobject]@{ suite_version='1.0.0'; results=$results.ToArray(); requested_harnesses=$HarnessTests; harnesses_enabled=[bool]$RunHarnesses; live_acceptance='NOT_RUN'; promotion='BLOCKED_PENDING_COMPLETE_EVIDENCE' } | ConvertTo-Json -Depth 8 | Set-Content (Join-Path $evidence 'results.json')
    Pop-Location
}
Write-Output "Requested Windows build/harness subset completed; NOT release acceptance. Evidence: $evidence"

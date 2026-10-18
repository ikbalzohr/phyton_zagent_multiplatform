# Shared Windows-only build prerequisites. No downloads or implicit SDK installation.
function Initialize-ZagentBuild {
    param([string]$Root, [string]$Dotnet = 'dotnet')
    if ($env:OS -ne 'Windows_NT') { throw 'Build/test/package execution is restricted to local Windows.' }
    $resolved = (Get-Command $Dotnet -CommandType Application -ErrorAction Stop).Source
    $required = (Get-Content (Join-Path $Root 'global.json') -Raw | ConvertFrom-Json).sdk.version
    Push-Location $Root
    try {
        $actual = (& $resolved --version | Out-String).Trim()
        if ($LASTEXITCODE -ne 0 -or $actual -ne $required) { throw "SDK mismatch: required=$required actual=$actual" }
    } finally { Pop-Location }
    $env:DOTNET_CLI_TELEMETRY_OPTOUT = '1'
    $env:DOTNET_SKIP_FIRST_TIME_EXPERIENCE = '1'
    return $resolved
}
function Publish-ZagentProject {
    param([string]$Root, [string]$Dotnet, [string]$Name, [string]$OutputRoot)
    $sdk = Initialize-ZagentBuild -Root $Root -Dotnet $Dotnet
    $out = Join-Path $OutputRoot $Name.ToLowerInvariant()
    if (Test-Path $out) { throw "Publish target must be fresh: $out" }
    & $sdk publish (Join-Path $Root "src\Zagent.$Name\Zagent.$Name.csproj") -c Release -r win-x64 --self-contained true -o $out '-p:PublishSingleFile=true' '-p:IncludeNativeLibrariesForSelfExtract=true' '-p:DebugType=None' '-p:DebugSymbols=false' --nologo
    if ($LASTEXITCODE -ne 0) { throw "Publish failed: $Name ($LASTEXITCODE)" }
}

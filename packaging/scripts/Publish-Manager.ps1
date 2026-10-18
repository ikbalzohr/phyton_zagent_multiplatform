param([string]$Dotnet = 'dotnet', [string]$OutputRoot = '')
# UI1 is hosted by Core. This historical script name is a build alias, not a second UI.
& (Join-Path $PSScriptRoot 'Publish-Core.ps1') -Dotnet $Dotnet -OutputRoot $OutputRoot

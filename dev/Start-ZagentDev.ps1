param([switch]$NoBuild, [string]$Dotnet = 'dotnet', [string]$DashboardConfig = '', [string]$FilesProfile = '')
& (Join-Path $PSScriptRoot 'Start-Zagent-Dev.ps1') @PSBoundParameters

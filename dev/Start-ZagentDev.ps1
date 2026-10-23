param([switch]$NoBuild, [string]$Dotnet = 'dotnet', [string]$DashboardConfig = '', [string]$DataRoot = '', [string]$FilesProfile = '', [string]$Python311 = '', [string]$WebNode = '')
& (Join-Path $PSScriptRoot 'Start-Zagent-Dev.ps1') @PSBoundParameters

param([string]$Dotnet = 'dotnet', [string]$OutputRoot = '')
$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
if (-not $OutputRoot) { $OutputRoot = Join-Path $root 'packaging\publish' }
. (Join-Path $PSScriptRoot 'Build-Common.ps1')
Publish-ZagentProject -Root $root -Dotnet $Dotnet -Name 'Bundle' -OutputRoot $OutputRoot

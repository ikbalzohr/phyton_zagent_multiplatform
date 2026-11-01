param([string]$Dotnet = 'dotnet', [string]$OutputRoot = '')
$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
if (-not $OutputRoot) { $OutputRoot = Join-Path $root 'packaging\publish' }
. (Join-Path $PSScriptRoot 'Build-Common.ps1')
# The shipped apphost is self-contained and single-file. It never requires
# another Zagent product's SDK/runtime or local checkout directory.
Publish-ZagentProject -Root $root -Dotnet $Dotnet -Name 'Launcher' -OutputRoot $OutputRoot

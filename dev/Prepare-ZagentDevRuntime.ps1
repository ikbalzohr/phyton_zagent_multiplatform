param([string]$RuntimeSource = '', [string]$RuntimeTarget = '')
& (Join-Path $PSScriptRoot 'Prepare-Zagent-DevRuntime.ps1') -RuntimeSource $RuntimeSource -RuntimeTarget $RuntimeTarget

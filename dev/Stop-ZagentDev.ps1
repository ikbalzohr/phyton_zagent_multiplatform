param([string]$PipeName = 'Zagent.Manager.Development')
& (Join-Path $PSScriptRoot 'Stop-Zagent-Dev.ps1') -PipeName $PipeName

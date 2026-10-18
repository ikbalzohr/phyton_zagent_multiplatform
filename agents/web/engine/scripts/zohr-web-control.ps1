param(
  [ValidateSet('start','stop','restart','status')]
  [string]$Action = 'status'
)

$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
$Port = 8021
$Health = 'http://127.0.0.1:8021/health'
$Entry = Join-Path $Root 'dist\index.js'

function Get-ZohrListener {
  $conn = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
  if (-not $conn) { return $null }
  $proc = Get-CimInstance Win32_Process -Filter "ProcessId=$($conn.OwningProcess)" -ErrorAction SilentlyContinue
  if (-not $proc) { return $null }
  [pscustomobject]@{
    Pid = [int]$conn.OwningProcess
    Name = $proc.Name
    CommandLine = $proc.CommandLine
  }
}

function Show-Status {
  $listener = Get-ZohrListener
  if (-not $listener) {
    Write-Host '[Zohr Web v2] STOPPED - port 8021 tidak listening.'
    return $false
  }
  Write-Host "[Zohr Web v2] RUNNING - PID $($listener.Pid) - $($listener.Name)"
  try {
    $resp = Invoke-WebRequest -UseBasicParsing -Uri $Health -TimeoutSec 3
    Write-Host "[Zohr Web v2] Health HTTP $($resp.StatusCode)"
  } catch {
    Write-Host "[Zohr Web v2] Listener aktif, tetapi health check belum siap."
  }
  return $true
}

function Stop-Zohr {
  $listener = Get-ZohrListener
  if (-not $listener) {
    Write-Host '[Zohr Web v2] Sudah berhenti.'
    return
  }
  if ($listener.Name -ne 'node.exe' -or $listener.CommandLine -notmatch 'dist[\\/]index\.js') {
    throw "Port $Port dipakai proses lain: PID $($listener.Pid) $($listener.Name). Tidak dihentikan."
  }
  Write-Host "[Zohr Web v2] Menghentikan PID $($listener.Pid)..."
  Stop-Process -Id $listener.Pid -Force
  for ($i=0; $i -lt 20; $i++) {
    Start-Sleep -Milliseconds 250
    if (-not (Get-ZohrListener)) { break }
  }
  if (Get-ZohrListener) { throw 'Zohr Web v2 belum berhenti dari port 8021.' }
  Write-Host '[Zohr Web v2] STOP PASS.'
}

function Start-Zohr {
  if (Show-Status) {
    Write-Host '[Zohr Web v2] Tidak membuka proses duplikat.'
    return
  }
  if (-not (Test-Path $Entry)) {
    throw 'dist\index.js tidak ditemukan. Jalankan INSTALL_ZOHR_WEB_v2.bat atau npm run build.'
  }
  Set-Location $Root
  Write-Host '[Zohr Web v2] Starting http://127.0.0.1:8021 ...'
  Write-Host '[Zohr Web v2] Terminal ini adalah runtime. Tutup dengan ZOHR_WEB_v2_STOP.bat, bukan dengan menutup Chrome.'
  & node $Entry
  $code = $LASTEXITCODE
  Write-Host "[Zohr Web v2] Runtime berhenti. Exit code: $code"
  exit $code
}

switch ($Action) {
  'status'  { [void](Show-Status) }
  'stop'    { Stop-Zohr }
  'start'   { Start-Zohr }
  'restart' { Stop-Zohr; Start-Sleep -Milliseconds 500; Start-Zohr }
}

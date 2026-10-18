param(
  [ValidateSet('start','stop','restart','reload','status','check')]
  [string]$Action='status'
)
$ErrorActionPreference='Stop'
$Root=Split-Path -Parent $PSScriptRoot
$Port=8021
$Health='http://127.0.0.1:8021/health'
$Entry=Join-Path $Root 'dist\index.js'
$PidFile=Join-Path $Root 'runtime\manager_web.pid'
$Logs=Join-Path $Root 'logs'
$OutLog=Join-Path $Logs 'manager-runtime.out.log'
$ErrLog=Join-Path $Logs 'manager-runtime.err.log'
New-Item -ItemType Directory -Path (Split-Path $PidFile),$Logs -Force | Out-Null

function Get-Listener {
 $c=Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue|Select-Object -First 1
 if(-not $c){return $null}
 $p=Get-CimInstance Win32_Process -Filter "ProcessId=$($c.OwningProcess)" -ErrorAction SilentlyContinue
 [pscustomobject]@{Pid=[int]$c.OwningProcess;Name=$p.Name;CommandLine=$p.CommandLine}
}
function Test-Health {
 try{$r=Invoke-WebRequest -UseBasicParsing -Uri $Health -TimeoutSec 2;return ($r.StatusCode -eq 200)}catch{return $false}
}
function Stop-Web {
 $l=Get-Listener
 if(-not $l){Remove-Item $PidFile -Force -ErrorAction SilentlyContinue;return}
 if($l.Name -ne 'node.exe' -or $l.CommandLine -notmatch 'dist[\\/]index\.js'){throw "Port $Port belongs to another process. Refusing to stop PID $($l.Pid)."}
 Stop-Process -Id $l.Pid -Force
 Remove-Item $PidFile -Force -ErrorAction SilentlyContinue
}
function Start-Web {
 if(Get-Listener){return}
 if(-not(Test-Path $Entry)){throw 'dist\index.js not found. Build Zohr Web first.'}
 $node=(Get-Command node.exe -ErrorAction Stop).Source
 $p=Start-Process -FilePath $node -ArgumentList ('"'+$Entry+'"') -WorkingDirectory $Root -WindowStyle Hidden -PassThru -RedirectStandardOutput $OutLog -RedirectStandardError $ErrLog
 Set-Content $PidFile $p.Id -Encoding ASCII
 for($i=0;$i -lt 50;$i++){if(Test-Health){return};Start-Sleep -Milliseconds 200}
 if(-not(Get-Process -Id $p.Id -ErrorAction SilentlyContinue)){throw 'Zohr Web exited before becoming ready.'}
}
function Show-Status {
 $l=Get-Listener
 [pscustomobject]@{ok=(Test-Health);listening=[bool]$l;port=$Port;pid=$(if($l){$l.Pid}else{$null})}|ConvertTo-Json -Compress
}
switch($Action){
 'start'{Start-Web;Show-Status}
 'stop'{Stop-Web;Show-Status}
 'restart'{Stop-Web;Start-Sleep -Milliseconds 400;Start-Web;Show-Status}
 'reload'{Show-Status}
 'status'{Show-Status}
 'check'{Show-Status}
}

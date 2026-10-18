param([string]$PipeName = 'Zagent.Manager.Development')
$ErrorActionPreference = 'Stop'
if ($env:OS -ne 'Windows_NT') { throw 'Local Windows only.' }
# Maintenance-only CurrentUser named pipe; same Core shutdown coordinator as HTTP.
# No PID-file kill fallback and no process-name/production path heuristic.
$pipe = [IO.Pipes.NamedPipeClientStream]::new('.', $PipeName, [IO.Pipes.PipeDirection]::InOut)
try {
    $pipe.Connect(1500)
    $reader = [IO.StreamReader]::new($pipe,[Text.UTF8Encoding]::new($false),$false,16384,$true)
    $writer = [IO.StreamWriter]::new($pipe,[Text.UTF8Encoding]::new($false),16384,$true)
    try {
        $writer.AutoFlush = $true
        $id = [Guid]::NewGuid().ToString('N')
        $writer.WriteLine((@{protocolVersion='1.0';requestId=$id;method='system.shutdown';parameters=$null} | ConvertTo-Json -Compress))
        $pending = $reader.ReadLineAsync()
        if (-not $pending.Wait(10000)) { throw 'Core shutdown acknowledgement timed out.' }
        $response = $pending.Result | ConvertFrom-Json
        if (-not $response.success -or $response.requestId -ne $id) { throw 'Core shutdown rejected or mismatched response.' }
        Write-Output 'Core accepted coordinated shutdown; verify offline state in local evidence.'
    } finally { $writer.Dispose(); $reader.Dispose() }
} finally { $pipe.Dispose() }

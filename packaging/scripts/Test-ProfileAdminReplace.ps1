# Real PowerShell/.NET overload regression; no product configuration or credentials.
$ErrorActionPreference = 'Stop'
$root = Join-Path ([IO.Path]::GetTempPath()) ('zagent-replace-fixture-' + [guid]::NewGuid().ToString('N'))
$null = [IO.Directory]::CreateDirectory($root)
$candidate = Join-Path $root 'candidate.json'
$target = Join-Path $root 'target.json'
$backup = Join-Path $root 'independent.bak'
try {
    [IO.File]::WriteAllText($candidate, '{"fixture":"next"}')
    [IO.File]::WriteAllText($target, '{"fixture":"before"}')
    [IO.File]::Copy($target, $backup)
    [IO.File]::Replace($candidate,$target,[System.Management.Automation.Language.NullString]::Value,$false)
    if ([IO.File]::ReadAllText($target) -cne '{"fixture":"next"}') { throw 'Target readback mismatch.' }
    if ([IO.File]::ReadAllText($backup) -cne '{"fixture":"before"}') { throw 'Independent backup changed.' }
    if ([IO.File]::Exists($candidate)) { throw 'Candidate was not consumed.' }
    Write-Output 'PASS File.Replace real-null overload; target readback and independent backup preserved. No live configuration touched.'
} finally {
    # Only the uniquely-created fixture directory is removed.
    if ([IO.Directory]::Exists($root)) { [IO.Directory]::Delete($root, $true) }
}

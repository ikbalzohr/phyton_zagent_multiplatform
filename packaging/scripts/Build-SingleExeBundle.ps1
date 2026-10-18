param(
  [string]$PayloadRoot = "",
  [string]$OutputFile = ""
)

$ErrorActionPreference = "Stop"
if ($env:OS -ne "Windows_NT") { throw "Local Windows only." }

$root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
if ([string]::IsNullOrWhiteSpace($PayloadRoot)) {
  $PayloadRoot = Join-Path $root "packaging\staging\Zagent-1.0.0"
}
$PayloadRoot = [IO.Path]::GetFullPath($PayloadRoot)

if ([string]::IsNullOrWhiteSpace($OutputFile)) {
  $OutputFile = Join-Path $root "packaging\bundle\Zagent-Setup-1.0.0.exe"
}
$OutputFile = [IO.Path]::GetFullPath($OutputFile)

$bundleDir = Split-Path $OutputFile -Parent
New-Item -ItemType Directory -Force -Path $bundleDir | Out-Null

$stub = Join-Path $root "packaging\publish\bundle\Zagent.Bundle.exe"
$python = Join-Path $root "packaging\runtime\arcmap-python-3.11.9\python.exe"
$manifest = Join-Path $PayloadRoot "payload-manifest.json"
$bundleStem = [IO.Path]::GetFileNameWithoutExtension($OutputFile)
$status = Join-Path $bundleDir ($bundleStem + ".build-status.json")
$log = Join-Path $bundleDir ($bundleStem + ".build.log")
$zip = Join-Path $bundleDir ($bundleStem + ".payload.zip")
$payloadLeaf = Split-Path $PayloadRoot -Leaf
$candidate = if($payloadLeaf -match "-(rc\d+)$"){ $Matches[1] } else { "custom" }

function Save-Status([string]$state,[string]$message,[int]$code) {
  [pscustomobject]@{
    state=$state
    message=$message
    exit_code=$code
    payload_root=$PayloadRoot
    output_file=$OutputFile
    updated_at=[DateTimeOffset]::UtcNow.ToString("o")
  } | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $status -Encoding UTF8
}

try {
  Save-Status "RUNNING" "Validating bundle inputs." -1

  foreach($required in @($stub,$python,$manifest)) {
    if(-not (Test-Path -LiteralPath $required -PathType Leaf)) {
      throw "Required bundle input missing: $required"
    }
  }

  if(Test-Path -LiteralPath $OutputFile) {
    throw "Bundle output already exists. Refusing to overwrite: $OutputFile"
  }
  if(Test-Path -LiteralPath $zip) {
    throw "Payload ZIP already exists. Refusing to overwrite: $zip"
  }

  $zipScript = Join-Path $bundleDir ($bundleStem + ".zip_payload.py")
  $zipSource = @'
import hashlib
import json
import os
import sys
import zipfile

src = os.path.abspath(sys.argv[1])
dst = os.path.abspath(sys.argv[2])
manifest_path = os.path.join(src, "payload-manifest.json")

with open(manifest_path, "r", encoding="utf-8-sig") as handle:
    manifest = json.load(handle)

entries = manifest.get("files", [])
if manifest.get("file_count") != len(entries):
    raise RuntimeError("Payload manifest file_count is inconsistent.")

files = []
declared = set()

for entry in entries:
    rel = str(entry["path"]).replace("\\", "/")
    normalized = os.path.normpath(rel.replace("/", os.sep))
    if os.path.isabs(normalized) or normalized.startswith(".." + os.sep) or normalized == "..":
        raise RuntimeError(f"Manifest path escapes payload root: {rel}")

    path = os.path.abspath(os.path.join(src, normalized))
    if not path.startswith(src + os.sep):
        raise RuntimeError(f"Manifest path escapes payload root: {rel}")
    if not os.path.isfile(path):
        raise RuntimeError(f"Manifest file missing: {rel}")

    size = os.path.getsize(path)
    if size != int(entry["size"]):
        raise RuntimeError(f"Manifest size mismatch: {rel}")

    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)

    actual = digest.hexdigest()
    if actual.lower() != str(entry["sha256"]).lower():
        raise RuntimeError(f"Manifest SHA256 mismatch: {rel}")

    if rel.lower() in declared:
        raise RuntimeError(f"Duplicate manifest path: {rel}")

    declared.add(rel.lower())
    files.append((path, rel))

files.append((manifest_path, "payload-manifest.json"))

total = len(files)
with zipfile.ZipFile(
    dst,
    "w",
    compression=zipfile.ZIP_DEFLATED,
    compresslevel=6,
    allowZip64=True,
) as zf:
    for i, (path, rel) in enumerate(files, 1):
        zf.write(path, rel)
        if i % 250 == 0 or i == total:
            print(f"ZIP {i}/{total}", flush=True)

extra_files = 0
for walk_root, dirs, names in os.walk(src):
    dirs.sort()
    names.sort()
    for name in names:
        path = os.path.join(walk_root, name)
        rel = os.path.relpath(path, src).replace(os.sep, "/")
        if rel != "payload-manifest.json" and rel.lower() not in declared:
            extra_files += 1

if extra_files:
    raise RuntimeError(f"Unmanifested files found: {extra_files}")

print(
    f"ZIP_DONE files={total} ignored_non_manifest_files={extra_files}",
    flush=True,
)
'@
  [IO.File]::WriteAllText($zipScript,$zipSource,[Text.UTF8Encoding]::new($false))

  Save-Status "RUNNING" "Compressing production payload." -1
  & $python $zipScript $PayloadRoot $zip 2>&1 | Tee-Object -LiteralPath $log
  if($LASTEXITCODE -ne 0) {
    throw "Payload ZIP creation failed with exit code $LASTEXITCODE"
  }

  $stubInfo = Get-Item -LiteralPath $stub
  $zipInfo = Get-Item -LiteralPath $zip
  $offset = [long]$stubInfo.Length
  $length = [long]$zipInfo.Length
  $magic = [Text.Encoding]::ASCII.GetBytes("ZAGENTBUNDLE0001")

  Save-Status "RUNNING" "Assembling single-file installer." -1

  $out = [IO.File]::Open($OutputFile,[IO.FileMode]::CreateNew,[IO.FileAccess]::Write,[IO.FileShare]::None)
  try {
    foreach($path in @($stub,$zip)) {
      $input = [IO.File]::OpenRead($path)
      try { $input.CopyTo($out, 1048576) } finally { $input.Dispose() }
    }

    $out.Write($magic,0,$magic.Length)
    $offsetBytes = [BitConverter]::GetBytes($offset)
    $lengthBytes = [BitConverter]::GetBytes($length)
    $out.Write($offsetBytes,0,$offsetBytes.Length)
    $out.Write($lengthBytes,0,$lengthBytes.Length)
  }
  finally {
    $out.Dispose()
  }

  $final = Get-Item -LiteralPath $OutputFile
  $bundleHash = (Get-FileHash -LiteralPath $OutputFile -Algorithm SHA256).Hash.ToLowerInvariant()
  $zipHash = (Get-FileHash -LiteralPath $zip -Algorithm SHA256).Hash.ToLowerInvariant()
  $manifestHash = (Get-FileHash -LiteralPath $manifest -Algorithm SHA256).Hash.ToLowerInvariant()

  $metadata = [pscustomobject]@{
    schema_version="1.0"
    product="Zagent"
    version="1.0.0"
    candidate=$candidate
    platform="win-x64"
    installer="single-exe-self-contained"
    installer_file=[IO.Path]::GetFileName($OutputFile)
    installer_size_bytes=$final.Length
    installer_size_mb=[math]::Round($final.Length/1MB,2)
    installer_sha256=$bundleHash
    payload_zip_size_bytes=$length
    payload_zip_sha256=$zipHash
    payload_manifest_sha256=$manifestHash
    stub_size_bytes=$offset
    footer_magic="ZAGENTBUNDLE0001"
    signed=$false
    browser_policy="Google Chrome external; no Chromium/Firefox/WebKit; FFmpeg helper only"
    user_data_uninstall_default="preserve"
    generated_at_utc=[DateTimeOffset]::UtcNow.ToString("o")
  }

  $metadataPath = [IO.Path]::ChangeExtension($OutputFile,".json")
  [IO.File]::WriteAllText(
    $metadataPath,
    (($metadata | ConvertTo-Json -Depth 6) + [Environment]::NewLine),
    [Text.UTF8Encoding]::new($false)
  )

  Remove-Item -LiteralPath $zipScript -Force -ErrorAction SilentlyContinue

  Save-Status "PASS" ("Bundle ready. SHA256=" + $bundleHash) 0
  $metadata | ConvertTo-Json -Depth 6
}
catch {
  $_ | Out-String | Add-Content -LiteralPath $log -Encoding UTF8
  Save-Status "FAILED" $_.Exception.Message 1
  exit 1
}
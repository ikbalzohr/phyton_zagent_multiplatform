[CmdletBinding()]
param(
    [string]$Source = '',
    [string]$Destination = ''
)

$ErrorActionPreference = 'Stop'
$repo = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..'))
if (-not $Source) { $Source = Join-Path $repo 'image\zohrsystem.png' }
if (-not $Destination) { $Destination = Join-Path $repo 'image\zohrsystem.ico' }
$Source = [IO.Path]::GetFullPath($Source)
$Destination = [IO.Path]::GetFullPath($Destination)
if (-not (Test-Path -LiteralPath $Source -PathType Leaf)) { throw 'Launcher PNG asset is missing.' }
if ([IO.Path]::GetExtension($Source).ToLowerInvariant() -ne '.png' -or
    [IO.Path]::GetExtension($Destination).ToLowerInvariant() -ne '.ico') {
    throw 'Launcher icon converter expects PNG input and ICO output.'
}
if ($Source -ieq $Destination) { throw 'Source and destination must differ.' }

Add-Type -AssemblyName System.Drawing
$sizes = @(16, 24, 32, 48, 64, 128, 256)
$sourceImage = [Drawing.Image]::FromFile($Source)
$frames = [Collections.Generic.List[byte[]]]::new()
try {
    if ($sourceImage.Width -ne $sourceImage.Height -or $sourceImage.Width -lt 256) {
        throw 'Launcher source image must be square and at least 256px.'
    }
    foreach ($size in $sizes) {
        $image = [Drawing.Bitmap]::new($size, $size, [Drawing.Imaging.PixelFormat]::Format32bppArgb)
        try {
            $graphic = [Drawing.Graphics]::FromImage($image)
            try {
                $graphic.Clear([Drawing.Color]::Transparent)
                $graphic.InterpolationMode = [Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic
                $graphic.SmoothingMode = [Drawing.Drawing2D.SmoothingMode]::HighQuality
                $graphic.PixelOffsetMode = [Drawing.Drawing2D.PixelOffsetMode]::HighQuality
                $graphic.CompositingQuality = [Drawing.Drawing2D.CompositingQuality]::HighQuality
                $graphic.DrawImage($sourceImage, [Drawing.Rectangle]::new(0, 0, $size, $size))
            } finally { $graphic.Dispose() }
            $frameStream = [IO.MemoryStream]::new()
            try {
                if ($size -eq 256) {
                    # Windows Vista+ supports compressed PNG for the 256px frame.
                    $image.Save($frameStream, [Drawing.Imaging.ImageFormat]::Png)
                } else {
                    # Legacy Windows icon consumers expect a bottom-up 32bpp
                    # DIB with doubled header height and an AND mask. PNG in
                    # small ICO frames is not handled consistently by Win32.
                    $frameWriter = [IO.BinaryWriter]::new($frameStream, [Text.Encoding]::UTF8, $true)
                    try {
                        $maskStride = [int]([Math]::Ceiling($size / 32.0) * 4)
                        $frameWriter.Write([uint32]40)
                        $frameWriter.Write([int32]$size)
                        $frameWriter.Write([int32](2 * $size))
                        $frameWriter.Write([uint16]1)
                        $frameWriter.Write([uint16]32)
                        $frameWriter.Write([uint32]0)
                        $frameWriter.Write([uint32]($size * $size * 4))
                        foreach ($unused in 1..4) { $frameWriter.Write([int32]0) }
                        $mask = New-Object byte[] ($size * $maskStride)
                        for ($y = $size - 1; $y -ge 0; $y--) {
                            for ($x = 0; $x -lt $size; $x++) {
                                $color = $image.GetPixel($x, $y)
                                $frameWriter.Write([byte]$color.B)
                                $frameWriter.Write([byte]$color.G)
                                $frameWriter.Write([byte]$color.R)
                                $frameWriter.Write([byte]$color.A)
                                if ($color.A -lt 128) {
                                    $maskRow = $size - 1 - $y
                                    $idx = $maskRow * $maskStride + [int][Math]::Floor($x / 8)
                                    $mask[$idx] = $mask[$idx] -bor [byte](1 -shl (7 - ($x % 8)))
                                }
                            }
                        }
                        $frameWriter.Write($mask)
                        $frameWriter.Flush()
                    } finally { $frameWriter.Dispose() }
                }
                $frames.Add($frameStream.ToArray())
            } finally { $frameStream.Dispose() }
        } finally { $image.Dispose() }
    }
} finally { $sourceImage.Dispose() }

$stream = [IO.MemoryStream]::new()
$writer = [IO.BinaryWriter]::new($stream)
try {
    $writer.Write([uint16]0)
    $writer.Write([uint16]1)
    $writer.Write([uint16]$frames.Count)
    $offset = [uint32](6 + 16 * $frames.Count)
    for ($i = 0; $i -lt $frames.Count; $i++) {
        $size = $sizes[$i]
        $writer.Write([byte]($size -band 255))
        $writer.Write([byte]($size -band 255))
        $writer.Write([byte]0)
        $writer.Write([byte]0)
        $writer.Write([uint16]1)
        $writer.Write([uint16]32)
        $writer.Write([uint32]$frames[$i].Length)
        $writer.Write([uint32]$offset)
        $offset += [uint32]$frames[$i].Length
    }
    foreach ($frame in $frames) { $writer.Write($frame) }
    $writer.Flush()
    $iconBytes = $stream.ToArray()
} finally {
    $writer.Dispose()
    $stream.Dispose()
}
$dir = [IO.Path]::GetDirectoryName($Destination)
if (-not (Test-Path -LiteralPath $dir -PathType Container)) {
    [IO.Directory]::CreateDirectory($dir) | Out-Null
}
[IO.File]::WriteAllBytes($Destination, $iconBytes)
$icon = [Drawing.Icon]::new($Destination)
try {
    if ($icon.Width -lt 16 -or $icon.Height -lt 16) { throw 'Generated ICO cannot be loaded.' }
} finally { $icon.Dispose() }
Write-Output ('LAUNCHER_ICON_OK sizes=' + ($sizes -join ',') +
    ' bytes=' + $iconBytes.Length +
    ' sha256=' + (Get-FileHash -LiteralPath $Destination -Algorithm SHA256).Hash)

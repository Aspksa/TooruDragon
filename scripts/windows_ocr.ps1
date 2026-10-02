param(
    [Parameter(Mandatory = $true)]
    [string]$InputPath
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
$OutputEncoding = [Console]::OutputEncoding

Add-Type -AssemblyName System.Runtime.WindowsRuntime

$script:AsTaskGeneric = [System.WindowsRuntimeSystemExtensions].GetMethods() |
    Where-Object {
        $_.Name -eq "AsTask" -and
        $_.IsGenericMethod -and
        $_.GetParameters().Count -eq 1
    } |
    Select-Object -First 1

$script:AsTaskAction = [System.WindowsRuntimeSystemExtensions].GetMethods() |
    Where-Object {
        $_.Name -eq "AsTask" -and
        -not $_.IsGenericMethod -and
        $_.GetParameters().Count -eq 1
    } |
    Select-Object -First 1

function Await-Operation {
    param(
        [Parameter(Mandatory = $true)]$Operation,
        [Parameter(Mandatory = $true)][Type]$ResultType
    )
    $method = $script:AsTaskGeneric.MakeGenericMethod($ResultType)
    $task = $method.Invoke($null, @($Operation))
    $task.Wait()
    return $task.Result
}

function Await-Action {
    param([Parameter(Mandatory = $true)]$Action)
    $task = $script:AsTaskAction.Invoke($null, @($Action))
    $task.Wait()
}

function Invoke-OcrBitmap {
    param(
        [Parameter(Mandatory = $true)]$SoftwareBitmap,
        [Parameter(Mandatory = $true)]$Engine,
        [Parameter(Mandatory = $true)][int]$PageNumber
    )

    $result = Await-Operation ($Engine.RecognizeAsync($SoftwareBitmap)) ([Windows.Media.Ocr.OcrResult])
    $blocks = @()
    foreach ($line in $result.Lines) {
        foreach ($word in $line.Words) {
            $rect = $word.BoundingRect
            $blocks += [PSCustomObject]@{
                text = $word.Text
                left = [double]$rect.X
                top = [double]$rect.Y
                width = [double]$rect.Width
                height = [double]$rect.Height
                confidence = 0.78
            }
        }
    }

    return [PSCustomObject]@{
        page_number = $PageNumber
        text = $result.Text
        confidence = 0.78
        engine = "windows_media_ocr"
        blocks = $blocks
        tables = @()
    }
}

function Get-BitmapFromStream {
    param([Parameter(Mandatory = $true)]$Stream)

    $decoder = Await-Operation ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($Stream)) ([Windows.Graphics.Imaging.BitmapDecoder])
    return Await-Operation ($decoder.GetSoftwareBitmapAsync(
        [Windows.Graphics.Imaging.BitmapPixelFormat]::Bgra8,
        [Windows.Graphics.Imaging.BitmapAlphaMode]::Premultiplied
    )) ([Windows.Graphics.Imaging.SoftwareBitmap])
}

$resolved = (Resolve-Path -LiteralPath $InputPath).Path
$file = Await-Operation ([Windows.Storage.StorageFile]::GetFileFromPathAsync($resolved)) ([Windows.Storage.StorageFile])

$engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromUserProfileLanguages()
if ($null -eq $engine) {
    throw "Windows OCR engine is unavailable for the current language profile."
}

$extension = [IO.Path]::GetExtension($resolved).ToLowerInvariant()
$pages = @()

if ($extension -eq ".pdf") {
    $pdf = Await-Operation ([Windows.Data.Pdf.PdfDocument]::LoadFromFileAsync($file)) ([Windows.Data.Pdf.PdfDocument])

    for ($index = 0; $index -lt $pdf.PageCount; $index++) {
        $page = $pdf.GetPage([uint32]$index)
        try {
            $stream = New-Object Windows.Storage.Streams.InMemoryRandomAccessStream
            try {
                Await-Action ($page.RenderToStreamAsync($stream))
                $stream.Seek(0)
                $bitmap = Get-BitmapFromStream $stream
                try {
                    $pages += Invoke-OcrBitmap -SoftwareBitmap $bitmap -Engine $engine -PageNumber ($index + 1)
                }
                finally {
                    if ($bitmap -is [IDisposable]) {
                        $bitmap.Dispose()
                    }
                }
            }
            finally {
                if ($stream -is [IDisposable]) {
                    $stream.Dispose()
                }
            }
        }
        finally {
            if ($page -is [IDisposable]) {
                $page.Dispose()
            }
        }
    }
}
else {
    $stream = Await-Operation ($file.OpenAsync([Windows.Storage.FileAccessMode]::Read)) ([Windows.Storage.Streams.IRandomAccessStreamWithContentType])
    try {
        $bitmap = Get-BitmapFromStream $stream
        try {
            $pages += Invoke-OcrBitmap -SoftwareBitmap $bitmap -Engine $engine -PageNumber 1
        }
        finally {
            if ($bitmap -is [IDisposable]) {
                $bitmap.Dispose()
            }
        }
    }
    finally {
        if ($stream -is [IDisposable]) {
            $stream.Dispose()
        }
    }
}

[PSCustomObject]@{
    pages = $pages
} | ConvertTo-Json -Depth 8 -Compress

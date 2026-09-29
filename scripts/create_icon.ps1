$ErrorActionPreference="Stop"
Add-Type -AssemblyName System.Drawing
$Root=(Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$dir=Join-Path $Root "assets\launcher"
New-Item -ItemType Directory -Force -Path $dir|Out-Null
$out=Join-Path $dir "toorudragon.ico"
$bmp=New-Object Drawing.Bitmap 64,64
$g=[Drawing.Graphics]::FromImage($bmp)
$g.SmoothingMode=[Drawing.Drawing2D.SmoothingMode]::AntiAlias
$g.Clear([Drawing.Color]::FromArgb(9,12,23))
$brush=New-Object Drawing.Drawing2D.LinearGradientBrush((New-Object Drawing.Rectangle(0,0,64,64)),[Drawing.Color]::FromArgb(94,231,255),[Drawing.Color]::FromArgb(255,74,185),45)
$g.FillEllipse($brush,5,5,54,54)
$inner=New-Object Drawing.SolidBrush([Drawing.Color]::FromArgb(9,12,23))
$g.FillEllipse($inner,11,11,42,42)
$font=New-Object Drawing.Font("Segoe UI",17,[Drawing.FontStyle]::Bold)
$white=New-Object Drawing.SolidBrush([Drawing.Color]::White)
$fmt=New-Object Drawing.StringFormat
$fmt.Alignment=[Drawing.StringAlignment]::Center;$fmt.LineAlignment=[Drawing.StringAlignment]::Center
$g.DrawString("TD",$font,$white,(New-Object Drawing.RectangleF(11,11,42,42)),$fmt)
$hIcon=$bmp.GetHicon()
$icon=[Drawing.Icon]::FromHandle($hIcon)
$fs=[IO.File]::Open($out,[IO.FileMode]::Create)
$icon.Save($fs);$fs.Close()
$g.Dispose();$bmp.Dispose();$brush.Dispose();$inner.Dispose();$font.Dispose();$white.Dispose()
Write-Host "Иконка создана: $out" -ForegroundColor Green

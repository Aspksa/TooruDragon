$ErrorActionPreference="Stop"
$Root=(Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$desktop=[Environment]::GetFolderPath("Desktop")
$link=Join-Path $desktop "TooruDragon.lnk"
$w=New-Object -ComObject WScript.Shell
$s=$w.CreateShortcut($link)
$s.TargetPath="$env:SystemRoot\System32\wscript.exe"
$s.Arguments='"' + (Join-Path $Root "TooruDragonLauncher.vbs") + '"'
$s.WorkingDirectory=$Root
$s.Description="TooruDragon Launcher"
$icon=Join-Path $Root "assets\launcher\toorudragon.ico"
if(-not(Test-Path $icon)){& powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $Root "scripts\create_icon.ps1") | Out-Null}
$s.IconLocation="$icon,0"
$s.Save()
Write-Host "Ярлык создан: $link" -ForegroundColor Green

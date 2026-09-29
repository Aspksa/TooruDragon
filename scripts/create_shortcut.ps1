$ErrorActionPreference="Stop"
$Root=(Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$desktop=[Environment]::GetFolderPath("Desktop")
$link=Join-Path $desktop "TooruDragon.lnk"
$w=New-Object -ComObject WScript.Shell
$s=$w.CreateShortcut($link)
$s.TargetPath=Join-Path $Root "TooruDragonLauncher.bat"
$s.WorkingDirectory=$Root
$s.Description="TooruDragon Launcher"
$s.IconLocation="$env:SystemRoot\System32\shell32.dll,44"
$s.Save()
Write-Host "Ярлык создан: $link" -ForegroundColor Green

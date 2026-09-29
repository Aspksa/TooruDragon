$ErrorActionPreference="SilentlyContinue"

if(Get-Command Unregister-ScheduledTask -ErrorAction SilentlyContinue){
    Unregister-ScheduledTask -TaskName "TooruDragon Launcher" -Confirm:$false
}

$startupDir=[Environment]::GetFolderPath("Startup")
$shortcut=Join-Path $startupDir "TooruDragon.lnk"
if(Test-Path $shortcut){
    Remove-Item $shortcut -Force
}

Write-Host "Автозапуск TooruDragon отключён." -ForegroundColor Yellow

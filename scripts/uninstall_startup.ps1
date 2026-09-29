$ErrorActionPreference="SilentlyContinue"
Unregister-ScheduledTask -TaskName "TooruDragon Launcher" -Confirm:$false
Write-Host "Автозапуск TooruDragon отключён." -ForegroundColor Yellow

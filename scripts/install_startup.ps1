$ErrorActionPreference="Stop"
$Root=(Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$launcher=Join-Path $Root "TooruDragonLauncher.vbs"
$task="TooruDragon Launcher"
$action=New-ScheduledTaskAction -Execute "wscript.exe" -Argument ('"{0}"' -f $launcher) -WorkingDirectory $Root
$trigger=New-ScheduledTaskTrigger -AtLogOn
$principal=New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited
$settings=New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -MultipleInstances IgnoreNew
Register-ScheduledTask -TaskName $task -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Force | Out-Null
Write-Host "Автозапуск TooruDragon включён." -ForegroundColor Green

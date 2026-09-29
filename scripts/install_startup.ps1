$ErrorActionPreference="Stop"
$Root=(Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$bat=Join-Path $Root "TooruDragonLauncher.bat"
$task="TooruDragon Launcher"
$action=New-ScheduledTaskAction -Execute "cmd.exe" -Argument ('/c "{0}"' -f $bat) -WorkingDirectory $Root
$trigger=New-ScheduledTaskTrigger -AtLogOn
$principal=New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited
$settings=New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -MultipleInstances IgnoreNew
Register-ScheduledTask -TaskName $task -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Force | Out-Null
Write-Host "Автозапуск TooruDragon включён." -ForegroundColor Green

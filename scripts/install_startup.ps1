$ErrorActionPreference="Stop"
$Root=(Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$launcher=Join-Path $Root "TooruDragonLauncher.vbs"
$task="TooruDragon Launcher"

try {
    if(-not(Get-Command Register-ScheduledTask -ErrorAction SilentlyContinue)){
        throw "Task Scheduler PowerShell API недоступен"
    }

    $action=New-ScheduledTaskAction -Execute "wscript.exe" -Argument ('"{0}" autostart' -f $launcher) -WorkingDirectory $Root
    $trigger=New-ScheduledTaskTrigger -AtLogOn
    $user=[System.Security.Principal.WindowsIdentity]::GetCurrent().Name
    $principal=New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Limited
    $settings=New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -MultipleInstances IgnoreNew
    Register-ScheduledTask -TaskName $task -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Force | Out-Null
    Write-Host "Автозапуск TooruDragon включён через Task Scheduler." -ForegroundColor Green
}
catch {
    $startupDir=[Environment]::GetFolderPath("Startup")
    $shortcut=Join-Path $startupDir "TooruDragon.lnk"
    $shell=New-Object -ComObject WScript.Shell
    $link=$shell.CreateShortcut($shortcut)
    $link.TargetPath="$env:SystemRoot\System32\wscript.exe"
    $link.Arguments='"' + $launcher + '" autostart'
    $link.WorkingDirectory=$Root
    $link.Description="TooruDragon Launcher AutoStart"
    $link.Save()
    Write-Host "Task Scheduler недоступен. Автозапуск включён через папку Startup." -ForegroundColor Yellow
}

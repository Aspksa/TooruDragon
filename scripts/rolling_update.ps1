param(
    [Parameter(Mandatory=$true)][string]$Python,
    [Parameter(Mandatory=$true)][string]$PreviousHead,
    [Parameter(Mandatory=$true)][string]$CurrentHead
)

$ErrorActionPreference="Stop"
$Root=(Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $Root

function Health([int]$Port){
    try{Invoke-RestMethod -Uri ("http://127.0.0.1:{0}/health" -f $Port) -TimeoutSec 1 | Out-Null;return $true}catch{return $false}
}

function Stop-Port([int]$Port){
    try{
        if(Get-Command Get-NetTCPConnection -ErrorAction SilentlyContinue){
            $conn=Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
            if($conn){Stop-Process -Id $conn.OwningProcess -Force -ErrorAction Stop;return}
        }
        $pattern=(":$Port\s+.*LISTENING\s+(\d+)$")
        $line=netstat -ano -p tcp | Select-String $pattern | Select-Object -First 1
        if($line -and $line.Matches.Count -gt 0){Stop-Process -Id ([int]$line.Matches[0].Groups[1].Value) -Force -ErrorAction Stop}
    }catch{}
}

function Wait-Up([int]$Port,[int]$Seconds=15){
    for($i=0;$i -lt ($Seconds*4);$i++){if(Health $Port){return $true};Start-Sleep -Milliseconds 250}
    return $false
}

function Start-Service([string]$Path){
    $full=Join-Path $Root $Path
    Start-Process -FilePath $Python -ArgumentList ("`"{0}`"" -f $full) -WorkingDirectory $Root -WindowStyle Hidden
}

function Restart-Core([string]$Name,[int]$Port,[string]$Path,[bool]$WasRunning){
    if(-not $WasRunning){Write-Host ("[UPDATE] {0} был выключен — состояние сохраняю." -f $Name) -ForegroundColor DarkGray;return $true}
    Write-Host ("[UPDATE] Перезапуск: {0}" -f $Name) -ForegroundColor Cyan
    Stop-Port $Port
    Start-Sleep -Milliseconds 350
    Start-Service $Path
    if(Wait-Up $Port){Write-Host ("[OK] {0} снова работает." -f $Name) -ForegroundColor Green;return $true}
    Write-Host ("[ERROR] {0} не прошёл health-check." -f $Name) -ForegroundColor Red
    return $false
}

function Supervisor-Post([string]$Path,[hashtable]$Body){
    try{
        $headers=@{}
        if($env:TOORUDRAGON_API_TOKEN){$headers["Authorization"]="Bearer "+$env:TOORUDRAGON_API_TOKEN}
        $json=$Body|ConvertTo-Json -Compress
        return Invoke-RestMethod -Uri ("http://127.0.0.1:8699"+$Path) -Method Post -ContentType "application/json; charset=utf-8" -Headers $headers -Body $json -TimeoutSec 25
    }catch{
        Write-Host ("[BLUE/GREEN] Supervisor API недоступен: {0}" -f $_.Exception.Message) -ForegroundColor Yellow
        return $null
    }
}

function Supervisor-Get([string]$Path){
    try{
        $headers=@{}
        if($env:TOORUDRAGON_API_TOKEN){$headers["Authorization"]="Bearer "+$env:TOORUDRAGON_API_TOKEN}
        return Invoke-RestMethod -Uri ("http://127.0.0.1:8699"+$Path) -Method Get -Headers $headers -TimeoutSec 10
    }catch{
        return $null
    }
}

function BlueGreen-Restart($Service,[bool]$WasRunning){
    if(-not $WasRunning){
        Write-Host ("[UPDATE] {0} был выключен — состояние сохраняю." -f $Service.Name) -ForegroundColor DarkGray
        return $true
    }

    if((-not(Health 8698)) -or (-not(Health 8699))){
        Write-Host ("[BLUE/GREEN] Gateway/Supervisor недоступны для {0}; использую rolling restart." -f $Service.Name) -ForegroundColor Yellow
        return (Restart-Core $Service.Name $Service.Port $Service.Path $true)
    }

    $candidatePort=[int]$Service.Port+1000
    if(Health $candidatePort){Stop-Port $candidatePort;Start-Sleep -Milliseconds 300}

    Write-Host ("[BLUE/GREEN] Stage {0} на :{1}" -f $Service.Name,$candidatePort) -ForegroundColor Cyan
    $promoted=Supervisor-Post "/deployment/promote" @{core=$Service.Key;port=$candidatePort}
    if((-not $promoted) -or (-not $promoted.ok)){
        Write-Host ("[BLUE/GREEN] Candidate не поднялся для {0}; fallback rolling." -f $Service.Name) -ForegroundColor Yellow
        return (Restart-Core $Service.Name $Service.Port $Service.Path $true)
    }

    Write-Host ("[BLUE/GREEN] Трафик {0} переключён на candidate." -f $Service.Name) -ForegroundColor Cyan
    $canonicalOk=Restart-Core $Service.Name $Service.Port $Service.Path $true
    if(-not $canonicalOk){
        [void](Supervisor-Post "/deployment/rollback" @{core=$Service.Key})
        return $false
    }

    $completed=Supervisor-Post "/deployment/complete" @{core=$Service.Key}
    if($completed -and $completed.ok){
        Write-Host ("[BLUE/GREEN] {0}: canonical подтверждён, candidate завершён." -f $Service.Name) -ForegroundColor Green
        return $true
    }

    Write-Host ("[BLUE/GREEN] Не удалось завершить promote {0}; пробую route rollback." -f $Service.Name) -ForegroundColor Yellow
    $rolled=Supervisor-Post "/deployment/rollback" @{core=$Service.Key}
    return [bool]($rolled -and $rolled.ok)
}

$services=@(
    @{Key="tooru_ai";Name="Tooru/AI";Port=8701;Path="core\tooru_ai\app.py";Prefix="core/tooru_ai/"},
    @{Key="laboratory";Name="Лаборатория Tooru/AI";Port=8702;Path="core\workshop\app.py";Prefix="core/workshop/"},
    @{Key="home";Name="Домашнее ядро";Port=8703;Path="core\home\app.py";Prefix="core/home/"},
    @{Key="work";Name="Рабочее ядро";Port=8704;Path="core\work\app.py";Prefix="core/work/"},
    @{Key="mobile";Name="Мобильное ядро";Port=8705;Path="core\mobile\app.py";Prefix="core/mobile/"},
    @{Key="main";Name="Главное ядро";Port=8700;Path="core\main\app.py";Prefix="core/main/"}
)

$running=@{}
foreach($s in $services){$running[$s.Key]=Health $s.Port}
try{$webRunning=[bool](Get-NetTCPConnection -LocalPort 8710 -State Listen -ErrorAction SilentlyContinue)}catch{$webRunning=$false}
$gatewayRunning=Health 8698
$supervisorRunning=Health 8699

$gatewayConfigured=$false
$supervisorConfigured=$false
try{
    $systemConfig=Get-Content (Join-Path $Root "config\system.json") -Raw -Encoding UTF8 | ConvertFrom-Json
    if($systemConfig.gateway){$gatewayConfigured=[bool]$systemConfig.gateway.enabled}
    if($systemConfig.supervisor){$supervisorConfigured=[bool]$systemConfig.supervisor.enabled}
}catch{}
$gatewayShouldRun=($gatewayRunning -or $gatewayConfigured)
$supervisorShouldRun=($supervisorRunning -or $supervisorConfigured)

$changedRaw=& git diff --name-only $PreviousHead $CurrentHead
$changed=@($changedRaw | ForEach-Object {$_.Trim().Replace("\","/")} | Where-Object {$_})
Write-Host ("[UPDATE] Изменено файлов: {0}" -f $changed.Count) -ForegroundColor Cyan

$restartAll=$false
foreach($file in $changed){
    if($file.StartsWith("core/system/") -or $file.StartsWith("config/") -or $file.StartsWith("data/") -or $file -eq "scripts/init_db.py"){$restartAll=$true;break}
}

$targets=@()
foreach($s in $services){
    $needed=$restartAll
    if(-not $needed){foreach($file in $changed){if($file.StartsWith($s.Prefix)){$needed=$true;break}}}
    if($needed){$targets += $s}
}

$webChanged=$restartAll
$gatewayChanged=$restartAll
$supervisorChanged=$restartAll
if(-not $webChanged){foreach($file in $changed){if($file.StartsWith("web/")){$webChanged=$true;break}}}
if(-not $gatewayChanged){foreach($file in $changed){if($file.StartsWith("gateway/")){$gatewayChanged=$true;break}}}
if(-not $supervisorChanged){foreach($file in $changed){if($file.StartsWith("supervisor/")){$supervisorChanged=$true;break}}}

& $Python "scripts\init_db.py"
if($LASTEXITCODE -ne 0){Write-Host "[ERROR] Миграция БД завершилась ошибкой." -ForegroundColor Red;& $Python "scripts\finalize_update.py" --rollback;exit 21}

$failed=$false
foreach($s in ($targets | Where-Object {$_.Key -ne "main"})){
    if(-not(BlueGreen-Restart $s $running[$s.Key])){$failed=$true;break}
}

if((-not $failed) -and $gatewayShouldRun -and ($gatewayChanged -or -not(Health 8698))){
    Write-Host "[UPDATE] Запуск/перезапуск Gateway" -ForegroundColor Cyan
    if(Health 8698){Stop-Port 8698;Start-Sleep -Milliseconds 300}
    Start-Service "gateway\app.py"
    if(-not(Wait-Up 8698 12)){$failed=$true}
}

if((-not $failed) -and $webChanged -and $webRunning){
    Write-Host "[UPDATE] Перезапуск Web UI" -ForegroundColor Cyan
    Stop-Port 8710
    Start-Service "web\server.py"
    Start-Sleep -Milliseconds 700
}

if(-not $failed){
    $mainTarget=$targets | Where-Object {$_.Key -eq "main"} | Select-Object -First 1
    if($mainTarget){if(-not(Restart-Core $mainTarget.Name $mainTarget.Port $mainTarget.Path $running["main"])){$failed=$true}}
}

if((-not $failed) -and $supervisorShouldRun -and ($supervisorChanged -or -not(Health 8699))){
    Write-Host "[UPDATE] Запуск/перезапуск External Supervisor" -ForegroundColor Cyan
    if(Health 8699){Stop-Port 8699;Start-Sleep -Milliseconds 300}
    Start-Service "supervisor\app.py"
    if(-not(Wait-Up 8699 12)){$failed=$true}
}

if(-not $failed){
    Start-Sleep -Seconds 2
    foreach($s in $services){
        if($running[$s.Key] -and -not(Health $s.Port)){
            Write-Host ("[ERROR] После обновления не отвечает ранее работавший сервис: {0}" -f $s.Name) -ForegroundColor Red
            $failed=$true
            break
        }
    }
    if((-not $failed) -and $gatewayShouldRun -and -not(Health 8698)){$failed=$true;Write-Host "[ERROR] Gateway не отвечает после обновления." -ForegroundColor Red}
    if((-not $failed) -and $supervisorShouldRun -and -not(Health 8699)){$failed=$true;Write-Host "[ERROR] Supervisor не отвечает после обновления." -ForegroundColor Red}
    if(-not $failed){
        & $Python "scripts\finalize_update.py" --success
        Write-Host "[UPDATE] Rolling update завершён успешно. Состояние сервисов сохранено." -ForegroundColor Green
        exit 0
    }
}

Write-Host "[ROLLBACK] Новая версия не прошла проверку. Возвращаю предыдущую." -ForegroundColor Yellow
if(Health 8699){
    $deployments=Supervisor-Get "/deployments"
    if($deployments -and $deployments.deployments){
        foreach($property in $deployments.deployments.PSObject.Properties){
            [void](Supervisor-Post "/deployment/rollback" @{core=$property.Name})
        }
    }
}
foreach($s in $services){if($running[$s.Key]){Stop-Port $s.Port}}
if($webRunning){Stop-Port 8710}
if($supervisorRunning){Stop-Port 8699}
if($gatewayRunning){Stop-Port 8698}
& $Python "scripts\finalize_update.py" --rollback
if($LASTEXITCODE -ne 0){exit 31}

if($gatewayRunning){Start-Service "gateway\app.py";[void](Wait-Up 8698 12)}
if($supervisorRunning){Start-Service "supervisor\app.py";[void](Wait-Up 8699 12)}
foreach($s in ($services | Where-Object {$_.Key -ne "main"})){if($running[$s.Key]){Start-Service $s.Path}}
Start-Sleep -Milliseconds 1200
if($running["main"]){Start-Service "core\main\app.py"}
if($webRunning){Start-Service "web\server.py"}
Start-Sleep -Seconds 2
$rollbackOk=$true
foreach($s in $services){
    if($running[$s.Key] -and -not(Health $s.Port)){$rollbackOk=$false;break}
}
if($rollbackOk -and $gatewayRunning -and -not(Health 8698)){$rollbackOk=$false}
if($rollbackOk -and $supervisorRunning -and -not(Health 8699)){$rollbackOk=$false}
if($rollbackOk){Write-Host "[ROLLBACK] Предыдущая версия восстановлена, прежнее состояние сервисов возвращено." -ForegroundColor Green;exit 40}
Write-Host "[CRITICAL] Rollback выполнен, но один из ранее работавших сервисов не поднялся." -ForegroundColor Red
exit 41

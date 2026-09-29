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
if(-not $webChanged){foreach($file in $changed){if($file.StartsWith("web/")){$webChanged=$true;break}}}

& $Python "scripts\init_db.py"
if($LASTEXITCODE -ne 0){Write-Host "[ERROR] Миграция БД завершилась ошибкой." -ForegroundColor Red;& $Python "scripts\finalize_update.py" --rollback;exit 21}

$failed=$false
foreach($s in ($targets | Where-Object {$_.Key -ne "main"})){
    if(-not(Restart-Core $s.Name $s.Port $s.Path $running[$s.Key])){$failed=$true;break}
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

if(-not $failed){
    Start-Sleep -Seconds 2
    foreach($s in $services){
        if($running[$s.Key] -and -not(Health $s.Port)){
            Write-Host ("[ERROR] После обновления не отвечает ранее работавший сервис: {0}" -f $s.Name) -ForegroundColor Red
            $failed=$true
            break
        }
    }
    if(-not $failed){
        & $Python "scripts\finalize_update.py" --success
        Write-Host "[UPDATE] Rolling update завершён успешно. Состояние сервисов сохранено." -ForegroundColor Green
        exit 0
    }
}

Write-Host "[ROLLBACK] Новая версия не прошла проверку. Возвращаю предыдущую." -ForegroundColor Yellow
foreach($s in $services){if($running[$s.Key]){Stop-Port $s.Port}}
if($webRunning){Stop-Port 8710}
& $Python "scripts\finalize_update.py" --rollback
if($LASTEXITCODE -ne 0){exit 31}

foreach($s in ($services | Where-Object {$_.Key -ne "main"})){if($running[$s.Key]){Start-Service $s.Path}}
Start-Sleep -Milliseconds 1200
if($running["main"]){Start-Service "core\main\app.py"}
if($webRunning){Start-Service "web\server.py"}
Start-Sleep -Seconds 2
$rollbackOk=$true
foreach($s in $services){
    if($running[$s.Key] -and -not(Health $s.Port)){$rollbackOk=$false;break}
}
if($rollbackOk){Write-Host "[ROLLBACK] Предыдущая версия восстановлена, прежнее состояние сервисов возвращено." -ForegroundColor Green;exit 40}
Write-Host "[CRITICAL] Rollback выполнен, но один из ранее работавших сервисов не поднялся." -ForegroundColor Red
exit 41

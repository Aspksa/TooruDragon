param(
    [switch]$SkipUpdate,
    [switch]$SkipTests
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = (New-Object System.Text.UTF8Encoding -ArgumentList $false)
$OutputEncoding = [Console]::OutputEncoding
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $Root
$Host.UI.RawUI.WindowTitle = "🐉 TooruDragon v0.1.0 Alpha — Русский лаунчер"

function Write-Logo {
    Clear-Host
    Write-Host ""
    Write-Host "╔══════════════════════════════════════════════════════════════╗" -ForegroundColor DarkCyan
    Write-Host "║                🐉  T O O R U D R A G O N  🐉              ║" -ForegroundColor Cyan
    Write-Host "║                  v0.1.0 Alpha • Launcher                   ║" -ForegroundColor DarkCyan
    Write-Host "╚══════════════════════════════════════════════════════════════╝" -ForegroundColor DarkCyan
    Write-Host ""
}
function Write-Step([string]$Icon,[string]$Title,[ConsoleColor]$Color="Cyan"){ Write-Host ("  {0}  {1}" -f $Icon,$Title) -ForegroundColor $Color }
function Write-Ok([string]$Text){ Write-Step "✔" $Text "Green" }
function Write-Warn([string]$Text){ Write-Step "⚠" $Text "Yellow" }
function Write-Fail([string]$Text){ Write-Step "✖" $Text "Red" }
function Write-Info([string]$Text){ Write-Step "◆" $Text "Cyan" }

function Test-WritableFolder([string]$Path) {
    try {
        New-Item -ItemType Directory -Force -Path $Path | Out-Null
        $test = Join-Path $Path ".toorudragon-write-test"
        [IO.File]::WriteAllText($test,"ok",(New-Object System.Text.UTF8Encoding -ArgumentList $false))
        Remove-Item $test -Force
        return $true
    } catch { return $false }
}

function Get-PortablePythonPackage {
    $arch=$env:PROCESSOR_ARCHITECTURE
    if($env:PROCESSOR_ARCHITEW6432){$arch=$env:PROCESSOR_ARCHITEW6432}
    switch($arch.ToUpperInvariant()){
        "AMD64" { return @{Version="3.14.7";Url="https://www.python.org/ftp/python/3.14.7/python-3.14.7-embed-amd64.zip";Sha256="d297e5ff019966817ad8502465176139f2d3d840fa4ed84b13bed399a6ab1f15"} }
        "ARM64" { return @{Version="3.14.7";Url="https://www.python.org/ftp/python/3.14.7/python-3.14.7-embed-arm64.zip";Sha256="f6773983c8959d4281e48c4540cb0bdd23e42391e4e951ce17e7ceb52658f21c"} }
        "X86"   { return @{Version="3.14.7";Url="https://www.python.org/ftp/python/3.14.7/python-3.14.7-embed-win32.zip";Sha256="2bce2347adb05b4565d0bf50f7a44298f6c0bb08ae4f9d88d051b8512a55fcf7"} }
        default { throw "Неизвестная архитектура Windows: $arch" }
    }
}

function Find-Python {
    $portable=Join-Path $Root "runtime\python\python.exe"
    if(Test-Path $portable){ return $portable }
    foreach($cmd in @("python","py")){
        try {
            if($cmd -eq "py"){
                $path=& py -3 -c "import sys; print(sys.executable if sys.version_info >= (3,11) else '')" 2>$null
            } else {
                $path=& python -c "import sys; print(sys.executable if sys.version_info >= (3,11) else '')" 2>$null
            }
            if($LASTEXITCODE -eq 0 -and $path){ return ($path|Select-Object -First 1).Trim() }
        } catch {}
    }
    return $null
}

function Install-PortablePython {
    $package=Get-PortablePythonPackage
    $runtimeDir=Join-Path $Root "runtime"
    $pythonDir=Join-Path $runtimeDir "python"
    $zipPath=Join-Path $runtimeDir "python-portable.zip"
    New-Item -ItemType Directory -Force -Path $runtimeDir | Out-Null
    Write-Info "Python не найден. Загружаю переносной Python $($package.Version)..."
    [Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12
    Invoke-WebRequest -UseBasicParsing -Uri $package.Url -OutFile $zipPath
    Write-Info "Проверяю SHA-256 загруженного Python..."
    $actual=(Get-FileHash -Algorithm SHA256 -Path $zipPath).Hash.ToLowerInvariant()
    if($actual -ne $package.Sha256){
        Remove-Item $zipPath -Force -ErrorAction SilentlyContinue
        throw "SHA-256 не совпал. Файл удалён для безопасности."
    }
    Write-Ok "SHA-256 подтверждён"
    if(Test-Path $pythonDir){Remove-Item $pythonDir -Recurse -Force}
    New-Item -ItemType Directory -Force -Path $pythonDir | Out-Null
    Expand-Archive -Path $zipPath -DestinationPath $pythonDir -Force
    Remove-Item $zipPath -Force
    $pythonExe=Join-Path $pythonDir "python.exe"
    if(-not(Test-Path $pythonExe)){throw "Переносной Python распакован некорректно."}
    Write-Ok "Переносной Python готов: runtime\python"
    return $pythonExe
}

function Run-Preflight([string]$Python) {
    Write-Host ""
    Write-Host "  ─────────────── 🧪 ПОЛНАЯ ПРОВЕРКА ПЕРЕД ЗАПУСКОМ ───────────────" -ForegroundColor Magenta
    $failures=0
    if(Test-WritableFolder (Join-Path $Root "runtime")){Write-Ok "Носитель доступен для записи"}else{Write-Fail "Нет прав на запись в папку проекта";$failures++}

    try {
        $version=& $Python -c "import sys; print('.'.join(map(str, sys.version_info[:3])))"
        if($LASTEXITCODE -eq 0){Write-Ok "Python работает: $version"}else{throw "Код возврата $LASTEXITCODE"}
    } catch {Write-Fail "Python не запускается: $($_.Exception.Message)";$failures++}

    & $Python -c "import sqlite3, json, urllib.request, ssl, threading; print('ok')" *> $null
    if($LASTEXITCODE -eq 0){Write-Ok "Системные библиотеки Python доступны"}else{Write-Fail "Не прошла проверка библиотек Python";$failures++}

    & $Python -c "import json; [json.load(open(p, encoding='utf-8')) for p in ['config/system.json','config/cores.json','config/compatibility.json']]" *> $null
    if($LASTEXITCODE -eq 0){Write-Ok "JSON-конфигурация корректна и читается как UTF-8"}else{Write-Fail "Ошибка в системной JSON-конфигурации";$failures++}

    & $Python -m compileall -q "core" "scripts" "web" *> $null
    if($LASTEXITCODE -eq 0){Write-Ok "Python-код прошёл синтаксическую проверку"}else{Write-Fail "Обнаружена синтаксическая ошибка Python";$failures++}

    & $Python "scripts\init_db.py" *> $null
    if($LASTEXITCODE -eq 0){Write-Ok "SQLite и схема базы данных готовы"}else{Write-Fail "Ошибка инициализации базы данных";$failures++}

    $busy=@()
    if(Get-Command Get-NetTCPConnection -ErrorAction SilentlyContinue){
        foreach($port in 8700..8705){
            $listener=Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue
            if($listener){$busy+=$port}
        }
        if($busy.Count -eq 0){Write-Ok "Порты 8700–8705 свободны"}else{Write-Warn "Порты уже заняты: $($busy -join ', '). Возможно, TooruDragon уже запущен."}
    } else {
        Write-Warn "Системная проверка TCP-портов недоступна на этой версии Windows — продолжаю запуск"
    }

    $ruTest="Тору • Господин • Проверка русского языка • 🐉"
    try {
        $utfFile=Join-Path $Root "runtime\utf8-test.txt"
        [IO.File]::WriteAllText($utfFile,$ruTest,(New-Object System.Text.UTF8Encoding($false)))
        $readBack=[IO.File]::ReadAllText($utfFile,[Text.Encoding]::UTF8)
        Remove-Item $utfFile -Force
        if($readBack -eq $ruTest){Write-Ok "Русский язык и UTF-8 работают корректно"}else{throw "Текст после записи изменился"}
    } catch {Write-Fail "Проблема UTF-8/русского языка: $($_.Exception.Message)";$failures++}

    if(Get-Command git -ErrorAction SilentlyContinue){Write-Ok "Git найден — автообновление доступно"}else{Write-Warn "Git не найден — запуск возможен, но автообновление будет пропущено"}

    Write-Host ""
    if($failures -gt 0){Write-Fail "Проверка завершена с ошибками: $failures";return $false}
    Write-Ok "Все обязательные проверки пройдены"
    return $true
}

Write-Logo
Write-Info "Папка запуска: $Root"
Write-Info "Режим: переносимый — буква диска не важна"
$env:PYTHONUTF8="1"
$env:PYTHONIOENCODING="utf-8"

$python=Find-Python
if(-not $python){
    try{$python=Install-PortablePython}catch{
        Write-Fail "Не удалось подготовить Python: $($_.Exception.Message)"
        Write-Host "";Read-Host "Нажмите Enter для выхода";exit 10
    }
}else{Write-Ok "Python найден: $python"}

$pythonDir=Split-Path $python -Parent
$env:PATH="$pythonDir;$env:PATH"
$env:TOORUDRAGON_PYTHON=$python

if(-not $SkipUpdate){
    Write-Host ""
    Write-Host "  ─────────────────────── 🔄 ОБНОВЛЕНИЕ ───────────────────────" -ForegroundColor Magenta
    if(Get-Command git -ErrorAction SilentlyContinue){
        & $python "scripts\update.py"
        if($LASTEXITCODE -eq 0){Write-Ok "Репозиторий обновлён"}else{Write-Warn "Обновление не применено. Запускаю текущую локальную версию."}
    }else{Write-Warn "Git отсутствует — автообновление пропущено"}
}

if(-not $SkipTests){
    if(-not(Run-Preflight $python)){
        Write-Host "";Write-Fail "Запуск остановлен: сначала исправьте ошибки проверки."
        Read-Host "Нажмите Enter для выхода";exit 20
    }
}

Write-Host ""
Write-Host "  ─────────────────────── 🚀 ЗАПУСК ──────────────────────────" -ForegroundColor Magenta
Write-Info "Запускаю все ядра TooruDragon..."
$startScript=Join-Path $Root "scripts\start_all.bat"
& cmd.exe /d /c $startScript
if($LASTEXITCODE -ne 0){
    Write-Fail "Стартовый сценарий завершился с ошибкой: $LASTEXITCODE"
    Read-Host "Нажмите Enter для выхода";exit $LASTEXITCODE
}

Write-Host ""
Write-Host "╔══════════════════════════════════════════════════════════════╗" -ForegroundColor Green
Write-Host "║  ✔ TooruDragon запущен                                     ║" -ForegroundColor Green
Write-Host "║  🧠 Главное ядро:    http://127.0.0.1:8700                 ║" -ForegroundColor Green
Write-Host "║  🌐 Web UI:          http://127.0.0.1:8710                 ║" -ForegroundColor Green
Write-Host "║  🛡 Watchdog:        http://127.0.0.1:8700/watchdog        ║" -ForegroundColor Green
Write-Host "╚══════════════════════════════════════════════════════════════╝" -ForegroundColor Green
Write-Host ""
Read-Host "Нажмите Enter, чтобы закрыть только окно лаунчера"

@echo off
setlocal EnableExtensions
cd /d "%~dp0\.."

set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
set "PYTHON_EXE=%TOORUDRAGON_PYTHON%"
if not defined PYTHON_EXE (
    if exist "runtime\python\python.exe" (
        set "PYTHON_EXE=runtime\python\python.exe"
    ) else (
        set "PYTHON_EXE=python"
    )
)

"%PYTHON_EXE%" -c "import sys; print(sys.version)" >nul 2>nul
if errorlevel 1 (
    echo [ERROR] Python is unavailable.
    exit /b 1
)

echo [DB] Initializing database...
"%PYTHON_EXE%" "scripts\init_db.py"
if errorlevel 1 exit /b 2

"%PYTHON_EXE%" "scripts\desired_state.py" running --all
if errorlevel 1 exit /b 21

echo [GATEWAY] Checking local gateway...
"%PYTHON_EXE%" -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8698/health', timeout=0.5).read()" >nul 2>nul
if errorlevel 1 start "TooruDragon - Gateway" /min "%PYTHON_EXE%" "gateway\app.py"

echo [SUPERVISOR] Checking external supervisor...
"%PYTHON_EXE%" -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8699/health', timeout=0.5).read()" >nul 2>nul
if errorlevel 1 start "TooruDragon - Supervisor" /min "%PYTHON_EXE%" "supervisor\app.py"

echo [CORE] Starting Tooru AI...
start "TooruDragon - Tooru AI" /min "%PYTHON_EXE%" "core\tooru_ai\app.py"

echo [CORE] Starting Laboratory...
start "TooruDragon - Laboratory" /min "%PYTHON_EXE%" "core\workshop\app.py"

echo [CORE] Starting Home...
start "TooruDragon - Home" /min "%PYTHON_EXE%" "core\home\app.py"

echo [CORE] Starting Work...
start "TooruDragon - Work" /min "%PYTHON_EXE%" "core\work\app.py"

echo [CORE] Starting Mobile...
start "TooruDragon - Mobile" /min "%PYTHON_EXE%" "core\mobile\app.py"

timeout /t 2 /nobreak >nul

echo [CORE] Starting Main...
start "TooruDragon - Main" /min "%PYTHON_EXE%" "core\main\app.py"

echo [WEB] Starting Web Control Center...
start "TooruDragon - Web" /min "%PYTHON_EXE%" "web\server.py"

timeout /t 3 /nobreak >nul

echo [CHECK] Verifying services...
"%PYTHON_EXE%" "scripts\check_health.py"
if errorlevel 1 (
    echo [WARN] Not all services reported healthy.
    echo [ROLLBACK] Checking pending update...
    "%PYTHON_EXE%" "scripts\finalize_update.py" --rollback
    exit /b 3
)

"%PYTHON_EXE%" "scripts\finalize_update.py" --success >nul 2>nul

echo.
echo [OK] TooruDragon is running.
echo [URL] Gateway:          http://127.0.0.1:8698/health
echo [URL] Supervisor:       http://127.0.0.1:8699/status
echo [URL] Main:             http://127.0.0.1:8700
echo [URL] Tooru AI:         http://127.0.0.1:8701
echo [URL] Laboratory:       http://127.0.0.1:8702
echo [URL] Home:             http://127.0.0.1:8703
echo [URL] Work:             http://127.0.0.1:8704
echo [URL] Mobile:           http://127.0.0.1:8705
echo [URL] Web:              http://127.0.0.1:8710
exit /b 0

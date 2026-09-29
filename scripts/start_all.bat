@echo off
setlocal
cd /d "%~dp0\.."

where python >nul 2>nul
if errorlevel 1 (
    echo [ERROR] Python is not installed or not available in PATH.
    exit /b 1
)

echo [TooruDragon] Initializing database...
python "scripts\init_db.py"
if errorlevel 1 (
    echo [ERROR] Database initialization failed.
    exit /b 1
)

echo [TooruDragon] Starting Tooru/AI Core...
start "Tooru AI Core" cmd /k "core\tooru_ai\start.bat"

echo [TooruDragon] Starting Tooru/AI Laboratory Core...
start "Tooru AI Laboratory Core" cmd /k "core\workshop\start.bat"

echo [TooruDragon] Starting Home Core...
start "Tooru Home Core" cmd /k "core\home\start.bat"

echo [TooruDragon] Starting Work Core...
start "Tooru Work Core" cmd /k "core\work\start.bat"

echo [TooruDragon] Starting Mobile Core...
start "Tooru Mobile Core" cmd /k "core\mobile\start.bat"

timeout /t 2 /nobreak >nul

echo [TooruDragon] Starting Main Core...
start "TooruDragon Main Core" cmd /k "core\main\start.bat"

echo [TooruDragon] Starting Web UI...
start "TooruDragon Web" cmd /k "web\start.bat"

timeout /t 2 /nobreak >nul

echo.
echo [TooruDragon] Checking core health...
python "scripts\check_health.py"

echo.
echo [TooruDragon] Main Core:   http://127.0.0.1:8700
echo [TooruDragon] Tooru/AI:    http://127.0.0.1:8701
echo [TooruDragon] Laboratory:  http://127.0.0.1:8702
echo [TooruDragon] Home:        http://127.0.0.1:8703
echo [TooruDragon] Work:        http://127.0.0.1:8704
echo [TooruDragon] Mobile:      http://127.0.0.1:8705
echo [TooruDragon] Web UI:      http://127.0.0.1:8710
endlocal

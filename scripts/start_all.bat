@echo off
setlocal
cd /d "%~dp0\.."

where python >nul 2>nul
if errorlevel 1 (
    echo [ERROR] Python is not installed or not available in PATH.
    exit /b 1
)

echo [TooruDragon] Starting Tooru/AI Core...
start "Tooru AI Core" cmd /k "core\tooru_ai\start.bat"

echo [TooruDragon] Starting Workshop Core...
start "Tooru Workshop Core" cmd /k "core\workshop\start.bat"

echo [TooruDragon] Starting Home Core...
start "Tooru Home Core" cmd /k "core\home\start.bat"

echo [TooruDragon] Starting Work Core...
start "Tooru Work Core" cmd /k "core\work\start.bat"

timeout /t 2 /nobreak >nul

echo [TooruDragon] Starting Main Core...
start "TooruDragon Main Core" cmd /k "core\main\start.bat"

timeout /t 2 /nobreak >nul

echo.
echo [TooruDragon] Checking core health...
python "scripts\check_health.py"

endlocal

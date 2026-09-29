@echo off
setlocal
cd /d "%~dp0\.."

echo [TooruDragon] Starting Main Core...
if exist "core\main\start.bat" start "TooruDragon Main Core" cmd /k "core\main\start.bat"

echo [TooruDragon] Starting Tooru/AI Core...
if exist "core\tooru_ai\start.bat" start "Tooru AI Core" cmd /k "core\tooru_ai\start.bat"

echo [TooruDragon] Starting Workshop Core...
if exist "core\workshop\start.bat" start "Tooru Workshop Core" cmd /k "core\workshop\start.bat"

echo [TooruDragon] Starting Home Core...
if exist "core\home\start.bat" start "Tooru Home Core" cmd /k "core\home\start.bat"

echo [TooruDragon] Starting Work Core...
if exist "core\work\start.bat" start "Tooru Work Core" cmd /k "core\work\start.bat"

endlocal

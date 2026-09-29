@echo off
setlocal
title TooruDragon v0.1.0 Alpha

echo ==========================================
echo       TooruDragon v0.1.0 Alpha
echo ==========================================
echo.

cd /d "%~dp0"

where git >nul 2>nul
if errorlevel 1 (
    echo [ERROR] Git is not installed or not available in PATH.
    pause
    exit /b 1
)

where python >nul 2>nul
if errorlevel 1 (
    echo [ERROR] Python is not installed or not available in PATH.
    pause
    exit /b 1
)

echo [1/3] Checking updates...
git fetch origin main
if errorlevel 1 (
    echo [WARN] Update check failed. Starting current local version.
) else (
    git pull --ff-only origin main
    if errorlevel 1 (
        echo [WARN] Automatic update was not applied.
        echo [WARN] Local changes or branch divergence may require manual resolution.
    )
)

echo.
echo [2/3] Starting TooruDragon...
if exist "scripts\start_all.bat" (
    call "scripts\start_all.bat"
) else (
    echo [ERROR] scripts\start_all.bat not found.
    pause
    exit /b 1
)

echo.
echo [3/3] TooruDragon bootstrap finished.
echo Main Core: http://127.0.0.1:8700
echo Core status: http://127.0.0.1:8700/cores
echo.
pause
endlocal

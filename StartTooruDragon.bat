@echo off
setlocal EnableExtensions
cd /d "%~dp0"
title TooruDragon v0.3.0

set "TD_POWERSHELL=%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe"
if not exist "%TD_POWERSHELL%" (
    echo [ERROR] Windows PowerShell was not found:
    echo %TD_POWERSHELL%
    pause
    exit /b 10
)

"%TD_POWERSHELL%" -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\launcher.ps1"
set "EXIT_CODE=%ERRORLEVEL%"

if not "%EXIT_CODE%"=="0" (
    echo.
    echo [ERROR] TooruDragon launcher exited with code %EXIT_CODE%.
    pause
)

exit /b %EXIT_CODE%

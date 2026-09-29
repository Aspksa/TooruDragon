@echo off
setlocal EnableExtensions
chcp 65001 >nul
cd /d "%~dp0"
title TooruDragon Launcher
powershell.exe -NoLogo -NoProfile -STA -ExecutionPolicy Bypass -File "%~dp0launcherTooruDragonLauncher.ps1"
exit /b %ERRORLEVEL%

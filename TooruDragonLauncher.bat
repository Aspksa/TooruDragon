@echo off
setlocal EnableExtensions
chcp 65001 >nul
cd /d "%~dp0"
start "" wscript.exe "%~dp0TooruDragonLauncher.vbs"
exit /b 0

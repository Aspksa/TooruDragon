@echo off
setlocal EnableExtensions
chcp 65001 >nul
cd /d "%~dp0"
set "PYTHON_EXE=%TOORUDRAGON_PYTHON%"
if not defined PYTHON_EXE if exist "runtime\python\python.exe" set "PYTHON_EXE=runtime\python\python.exe"
if not defined PYTHON_EXE set "PYTHON_EXE=python"
echo [ВНИМАНИЕ] Будет восстановлен последний backup TooruDragon.
choice /M "Продолжить"
if errorlevel 2 exit /b 0
"%PYTHON_EXE%" "scripts\rollback.py"
pause

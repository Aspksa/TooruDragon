@echo off
setlocal EnableExtensions
cd /d "%~dp0\.."
set "PYTHON_EXE=%TOORUDRAGON_PYTHON%"
if not defined PYTHON_EXE (
    if exist "runtime\python\python.exe" (
        set "PYTHON_EXE=runtime\python\python.exe"
    ) else (
        set "PYTHON_EXE=python"
    )
)
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
"%PYTHON_EXE%" "web\server.py"

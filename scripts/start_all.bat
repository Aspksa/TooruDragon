@echo off
setlocal EnableExtensions
chcp 65001 >nul
cd /d "%~dp0\.."
set "PYTHON_EXE=%TOORUDRAGON_PYTHON%"
if not defined PYTHON_EXE set "PYTHON_EXE=python"
"%PYTHON_EXE%" -c "import sys; print(sys.version)" >nul 2>nul
if errorlevel 1 (
    echo [ОШИБКА] Python недоступен.
    exit /b 1
)
echo.
echo [БАЗА] Инициализация общей базы данных...
"%PYTHON_EXE%" "scripts\init_db.py"
if errorlevel 1 exit /b 2
echo [SUPERVISOR] Запуск внешнего Control Plane...
start "TooruDragon - Supervisor" cmd /k "chcp 65001>nul && set PYTHONUTF8=1 && set PYTHONIOENCODING=utf-8 && \"%PYTHON_EXE%\" \"supervisor\app.py\""
echo [ЯДРО] Запуск Tooru/AI...
start "TooruDragon - Tooru AI" cmd /k "chcp 65001>nul && set PYTHONUTF8=1 && set PYTHONIOENCODING=utf-8 && "core\tooru_ai\start.bat""
echo [ЯДРО] Запуск Лаборатории Tooru/AI...
start "TooruDragon - Лаборатория" cmd /k "chcp 65001>nul && set PYTHONUTF8=1 && set PYTHONIOENCODING=utf-8 && "core\workshop\start.bat""
echo [ЯДРО] Запуск Домашнего ядра...
start "TooruDragon - Дом" cmd /k "chcp 65001>nul && set PYTHONUTF8=1 && set PYTHONIOENCODING=utf-8 && "core\home\start.bat""
echo [ЯДРО] Запуск Рабочего ядра...
start "TooruDragon - Работа" cmd /k "chcp 65001>nul && set PYTHONUTF8=1 && set PYTHONIOENCODING=utf-8 && "core\work\start.bat""
echo [ЯДРО] Запуск Мобильного ядра...
start "TooruDragon - Mobile" cmd /k "chcp 65001>nul && set PYTHONUTF8=1 && set PYTHONIOENCODING=utf-8 && "core\mobile\start.bat""
timeout /t 2 /nobreak >nul
echo [ЯДРО] Запуск Главного ядра...
start "TooruDragon - Главное ядро" cmd /k "chcp 65001>nul && set PYTHONUTF8=1 && set PYTHONIOENCODING=utf-8 && "core\main\start.bat""
echo [WEB] Запуск русского Web UI...
start "TooruDragon - Web" cmd /k "chcp 65001>nul && set PYTHONUTF8=1 && set PYTHONIOENCODING=utf-8 && "web\start.bat""
timeout /t 3 /nobreak >nul
echo.
echo [ПРОВЕРКА] Проверяю состояние всех ядер...
"%PYTHON_EXE%" "scripts\check_health.py"
if errorlevel 1 (
    echo [ПРЕДУПРЕЖДЕНИЕ] Не все ядра подтвердили готовность.
    echo [ROLLBACK] Проверяю последнее обновление...
    "%PYTHON_EXE%" "scripts\finalize_update.py" --rollback
    exit /b 3
)
"%PYTHON_EXE%" "scripts\finalize_update.py" --success >nul 2>nul
echo.
echo [ГОТОВО] Все ядра отвечают.
echo [АДРЕС] Supervisor:    http://127.0.0.1:8699/status
echo [АДРЕС] Главное ядро:  http://127.0.0.1:8700
echo [АДРЕС] Service Registry: http://127.0.0.1:8700/registry
echo [АДРЕС] Tooru/AI:       http://127.0.0.1:8701
echo [АДРЕС] Лаборатория:    http://127.0.0.1:8702
echo [АДРЕС] Дом:            http://127.0.0.1:8703
echo [АДРЕС] Работа:         http://127.0.0.1:8704
echo [АДРЕС] Mobile:         http://127.0.0.1:8705
echo [АДРЕС] Web UI:         http://127.0.0.1:8710
exit /b 0

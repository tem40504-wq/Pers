@echo off
setlocal
cd /d "%~dp0"
echo ================================================
echo  LEVEL 9 PC-as-Brain: ПРОВЕРКА ПЕРЕД УСТАНОВКОЙ
echo ================================================
where py >nul 2>nul
if %ERRORLEVEL% EQU 0 (set "PY=py") else (set "PY=python")
%PY% --version >nul 2>nul
if errorlevel 1 (
  echo Python не найден. Установите Python 3.11+ вручную:
  echo https://www.python.org/downloads/windows/
  echo Ничего не устанавливается автоматически.
  pause
  exit /b 1
)
%PY% -m bootstrap.bootstrap --report
if errorlevel 1 (echo Проверка завершилась с ошибкой.)
echo.
echo Создание окружения только после отдельного согласия:
echo   %PY% -m bootstrap.bootstrap --create-venv
echo.
echo Проверка подключенного телефона:
echo   %PY% -m bootstrap.bootstrap --self-test
pause

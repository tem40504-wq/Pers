@echo off
setlocal
cd /d "%~dp0"
set "PYCMD=py"
where py >nul 2>nul
if errorlevel 1 set "PYCMD=python"
if exist "%~dp0.venv\Scripts\python.exe" set "PYCMD="%~dp0.venv\Scripts\python.exe""
if exist "%~dp0tools\android\platform-tools\adb.exe" set "PATH=%~dp0tools\android\platform-tools;%PATH%"
%PYCMD% main_pc_l9.py --preflight
if errorlevel 1 (
  echo Проверьте Python, ADB и подключение телефона.
  pause
  exit /b 1
)
echo.
echo ТЕСТОВЫЙ ЗАПУСК: 20 циклов, БЕЗ НАЖАТИЙ.
%PYCMD% main_pc_l9.py --steps 20 --dashboard
if errorlevel 1 echo Диагностика завершилась с ошибкой; см. вывод выше.
pause

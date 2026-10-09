@echo off
setlocal
chcp 65001 >nul
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
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
set "RESULT=%ERRORLEVEL%"
if not "%RESULT%"=="0" echo Диагностика завершилась с ошибкой; см. вывод выше.
echo Exit code: %RESULT%
pause
exit /b %RESULT%

@echo off
setlocal
chcp 65001 >nul
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
cd /d "%~dp0"
echo GameAgent v9.4 - Windows launcher
if not exist ".venv\Scripts\python.exe" goto missing
".venv\Scripts\python.exe" "launch_agent.py" %*
set "RESULT=%ERRORLEVEL%"
echo Exit code: %RESULT%
if /I not "%~1"=="--check-launcher" pause
exit /b %RESULT%
:missing
echo Run RUN_WINDOWS_TESTS.bat first to prepare the local Python environment.
if /I not "%~1"=="--check-launcher" pause
exit /b 2

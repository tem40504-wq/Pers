@echo off
setlocal
cd /d "%~dp0"
where py >nul 2>&1
if errorlevel 1 (
  echo Python not found. Please install Python 3.10+ manually.
  echo Official site: https://www.python.org/downloads/windows/
  pause
  exit /b 1
)
echo Universal Game Agent L5 SAFE TEST
 echo No packages are installed without explicit Y/N approval.
py main_l5.py --max-steps 5 --dashboard
pause

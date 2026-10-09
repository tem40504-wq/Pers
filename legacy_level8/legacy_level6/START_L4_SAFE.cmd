@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ========================================
echo Universal Game Agent Level 4 - SAFE
echo No automatic installations or downloads.
echo All changes require explicit Y/N.
echo ========================================
where py >nul 2>nul || (echo Python is missing. Install Python manually from https://www.python.org/downloads/ . & pause & exit /b 1)
py main_l4.py --game generic --max-steps 5
if errorlevel 1 echo Check the error message above.
pause

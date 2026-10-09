@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo Universal Game Agent L6 - SAFE MODE
where py >nul 2>nul
if errorlevel 1 (
 echo Python Launcher ne naiden. Ustanovite Python vruchnuyu; program ne skachivaet nichego bez soglasiya.
 pause
 exit /b 1
)
py main_l6.py --max-steps 5
pause

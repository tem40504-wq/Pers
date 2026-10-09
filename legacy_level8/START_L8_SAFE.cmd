@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo Level 8 Safety QA: никакой установки, никаких игровых нажатий.
py -m pytest -q tests/test_level8.py
if errorlevel 1 goto end
py main_l8.py --qa-demo
:end
pause

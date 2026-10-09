@echo off
setlocal
cd /d "%~dp0"
set "PYTHONUTF8=1"
py -3.13 run_windows_tests.py --prepare
set "RESULT=%ERRORLEVEL%"
echo.
echo Test report: reports\windows_test_report.json
echo Exit code: %RESULT%
pause
exit /b %RESULT%

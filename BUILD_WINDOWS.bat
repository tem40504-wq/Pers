@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0BUILD_WINDOWS.ps1"
if errorlevel 1 (
 echo.
 echo Build failed. Check Android SDK API 35 and JDK 17/21.
 pause
 exit /b 1
)
echo.
echo APK: app\build\outputs\apk\debug\app-debug.apk
pause

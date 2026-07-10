@echo off
setlocal
cd /d "%~dp0"
echo.
echo Restor-PC RescueGrid - USB Builder
echo.
set /p DRIVE=Lettre de la cle USB (ex: E:): 
set /p DASH=URL Dashboard (ex: http://192.168.1.10:8000, vide=localhost): 
if "%DASH%"=="" set DASH=http://localhost:8000
powershell -NoProfile -ExecutionPolicy Bypass -File "agent\windows\Create-RescueGridUSB.ps1" -TargetDrive "%DRIVE%" -DashboardUrl "%DASH%" -IncludeProject
pause

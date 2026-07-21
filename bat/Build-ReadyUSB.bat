@echo off
title Restor-PC - Pack USB pret a l'emploi
cd /d "%~dp0.."
net session >nul 2>&1
if %errorlevel% neq 0 (
  powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
  exit /b
)

echo.
echo Restor-PC RescueGrid - Pack USB
echo.
set /p DRIVE=Lettre de la cle USB (ex: E:): 
set /p DASH=URL Dashboard (ex: http://192.168.1.10:8000, vide=localhost): 
if "%DASH%"=="" set DASH=http://localhost:8000
echo.
echo Rendre la cle bootable WinPE (ADK) ? EFFACE la cle. (O/N)
set /p BOOT=Choix: 

if /i "%BOOT%"=="O" (
  powershell -NoProfile -ExecutionPolicy Bypass -File "agent\windows\winpe\Build-ReadyUSB.ps1" -TargetDrive "%DRIVE%" -DashboardUrl "%DASH%" -MakeBootable
) else (
  powershell -NoProfile -ExecutionPolicy Bypass -File "agent\windows\winpe\Build-ReadyUSB.ps1" -TargetDrive "%DRIVE%" -DashboardUrl "%DASH%"
)
echo.
pause

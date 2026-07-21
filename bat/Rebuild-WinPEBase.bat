@echo off
title Rebuild WinPE Microsoft de base (ADK)
cd /d "%~dp0.."
net session >nul 2>&1
if %errorlevel% neq 0 (
  powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
  exit /b
)
echo.
echo  Rebuild WinPE ADK (vrai Microsoft) + raccourcis bureau RescueGrid
echo  Ne formate PAS la cle - remplace seulement boot.wim
echo  Duree : 10-20 minutes
echo.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0..\agent\windows\winpe\Rebuild-WinPEBase.ps1" -BootWim "E:\sources\boot.wim"
echo.
echo Log : C:\WinPE_rebuild_base.log
pause

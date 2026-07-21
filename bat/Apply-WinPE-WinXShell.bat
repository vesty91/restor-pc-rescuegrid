@echo off
title Restor-PC - Strelec maison (WinXShell)
cd /d "%~dp0.."
net session >nul 2>&1
if %errorlevel% neq 0 (
  powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
  exit /b
)
echo.
echo  Injection WinXShell (bureau type Strelec) dans boot.wim
echo  Cle WINPE detectee automatiquement.
echo.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0..\agent\windows\winpe\Apply-WinPE-WinXShell.ps1" -BootWim "E:\sources\boot.wim"
echo.
echo Log: C:\WinPE_winxshell.log
pause

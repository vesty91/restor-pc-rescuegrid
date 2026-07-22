@echo off
chcp 65001 >nul
set PYTHONUTF8=1
title Restor-PC RescueGrid - Dashboard
cd /d "%~dp0.."
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0..\ps1\Start-Dashboard.ps1"
if errorlevel 1 pause
pause

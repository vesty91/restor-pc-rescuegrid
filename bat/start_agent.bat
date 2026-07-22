@echo off
chcp 65001 >nul
set PYTHONUTF8=1
title Restor-PC RescueGrid - Agent
cd /d "%~dp0.."
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0..\ps1\Start-Agent.ps1" -Interactive
if errorlevel 1 pause
pause

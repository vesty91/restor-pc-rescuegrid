@echo off
chcp 65001 >nul
set PYTHONUTF8=1
title Restor-PC RescueGrid - Tests
cd /d "%~dp0.."
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0..\ps1\Run-Tests.ps1"
set EXIT_CODE=%errorlevel%
if %EXIT_CODE% neq 0 pause
exit /b %EXIT_CODE%

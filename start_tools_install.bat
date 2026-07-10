@echo off
cd /d "%~dp0"
powershell -ExecutionPolicy Bypass -File "%~dp0Install-RescueGridTools.ps1"
pause

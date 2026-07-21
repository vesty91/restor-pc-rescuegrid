@echo off
cd /d "%~dp0.."
powershell -ExecutionPolicy Bypass -File "%~dp0..\ps1\Install-RescueGridTools.ps1"
pause

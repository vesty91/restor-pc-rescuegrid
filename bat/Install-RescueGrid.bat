@echo off
title Restor-PC RescueGrid - Installation
cd /d "%~dp0.."
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0..\ps1\Install-RescueGrid.ps1"
if errorlevel 1 pause

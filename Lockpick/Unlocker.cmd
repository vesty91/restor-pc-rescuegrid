@echo off
setlocal EnableDelayedExpansion
cd /d "%~dp0"
set "PS=%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe"
if not exist "%~dp0Unlocker-Menu.ps1" (
  echo Unlocker-Menu.ps1 introuvable.
  pause
  exit /b 1
)
start "" "%PS%" -NoProfile -STA -ExecutionPolicy Bypass -File "%~dp0Unlocker-Menu.ps1"

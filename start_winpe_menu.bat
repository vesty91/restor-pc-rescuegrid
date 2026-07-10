@echo off
title Restor-PC RescueGrid - WinPE Atelier
cd /d "%~dp0"

:: Verifier si le script WinPE existe
if not exist "agent\windows\Start-RescueGrid.ps1" (
    echo [ERREUR] Script WinPE introuvable : agent\windows\Start-RescueGrid.ps1
    pause
    exit /b 1
)

:: Verifier PowerShell
where powershell >nul 2>nul
if %errorlevel% neq 0 (
    echo [ERREUR] PowerShell requis pour le WinPE Atelier
    pause
    exit /b 1
)

echo =============================================
echo    Restor-PC RescueGrid - WinPE Atelier
echo =============================================
echo.
echo Lancement du menu WinPE...
echo.

powershell -ExecutionPolicy Bypass -File "agent\windows\Start-RescueGrid.ps1"

pause
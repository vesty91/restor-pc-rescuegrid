@echo off
chcp 65001 >nul
set PYTHONUTF8=1
title RescueGrid - Preparer install Windows sur cle FAT32
cd /d "%~dp0.."

echo.
echo Place ton ISO Windows, ou glisse-le sur cette fenetre.
echo.
set /p ISO=Chemin complet du .iso : 
if "%ISO%"=="" (
  echo Annule.
  pause
  exit /b 1
)

echo.
echo Recherche cle USB RescueGrid...
set "DRIVE="
for %%L in (E F G D H I) do (
  if exist "%%L:\RescueGrid\agent\windows\Start-RescueGrid.ps1" set "DRIVE=%%L:"
  if exist "%%L:\sources\boot.wim" if exist "%%L:\RescueGrid" set "DRIVE=%%L:"
)

if "%DRIVE%"=="" (
  echo Cle introuvable. Branche la cle WINPE/RescueGrid.
  pause
  exit /b 1
)

echo Cle : %DRIVE%
echo ISO : %ISO%
echo.
echo IMPORTANT : lancer en Administrateur (UAC) pour le split DISM.
echo.

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0..\agent\windows\winpe\Prepare-WindowsSetupUSB.ps1" -IsoPath "%ISO%" -TargetDrive %DRIVE%
echo.
pause

@echo off
chcp 65001 >nul
title Restor-PC RescueGrid - Lancement
color 0A

echo.
echo =============================================
echo    Restor-PC RescueGrid - Menu de lancement
echo =============================================
echo.
echo Choisissez une option :
echo.
echo 1. Lancer le Dashboard (backend FastAPI)
echo 2. Lancer l'Agent Windows (rapide)
echo 3. Menu technicien Windows (interactif)
echo 4. WinPE Atelier (menu 9 options)
echo 5. Build USB automatique
echo 6. PXE Rescue Server
echo 7. Ouvrir la documentation
echo 8. Quitter
echo.

set /p choix="Votre choix (1-8) : "

if "%choix%"=="1" goto dashboard
if "%choix%"=="2" goto agent
if "%choix%"=="3" goto agent_windows
if "%choix%"=="4" goto winpe
if "%choix%"=="5" goto build_usb
if "%choix%"=="6" goto pxe
if "%choix%"=="7" goto docs
if "%choix%"=="8" goto fin
goto fin

:dashboard
echo.
echo Lancement du Dashboard...
echo.
cd backend
python -m venv .venv 2>nul
.venv\Scripts\activate
pip install -r requirements.txt -q
echo.
echo Dashboard lance sur http://localhost:8000
echo Login : admin / rescuegrid2026
echo.
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
pause
goto fin

:agent
echo.
echo Lancement de l'Agent Windows...
echo.
powershell -ExecutionPolicy Bypass -File agent\windows\Invoke-RescueGrid.ps1 -ClientName "Client_Test" -BackupRoot "E:\RestorPC" -CreateZip
pause
goto fin

:agent_windows
echo.
echo Lancement du Menu technicien...
echo.
powershell -ExecutionPolicy Bypass -File agent\windows\Start-RescueGrid.ps1
pause
goto fin

:winpe
echo.
echo Lancement du WinPE Atelier...
echo.
powershell -ExecutionPolicy Bypass -File agent\windows\Start-RescueGrid.ps1
pause
goto fin

:build_usb
echo.
echo Build USB RescueGrid...
echo.
set /p lettre="Lettre du lecteur USB (ex: E) : "
powershell -ExecutionPolicy Bypass -File agent\windows\Build-RescueGridUSB.ps1 -UsbDriveLetter "%lettre%" -IncludeDataRecovery
pause
goto fin

:pxe
echo.
echo Configuration PXE Rescue Server...
echo.
set /p interface="Interface reseau (ex: Ethernet) : "
powershell -ExecutionPolicy Bypass -File agent\windows\Setup-PXERescueServer.ps1 -NetworkInterface "%interface%" -InstallTFTP -InstallHTTP
pause
goto fin

:docs
echo.
echo Ouverture de la documentation...
echo.
if exist DEMARRAGE_RAPIDE.md start "" DEMARRAGE_RAPIDE.md
if exist README.md start "" README.md
if exist README_LANCEMENT.md start "" README_LANCEMENT.md
if exist README_DEPLOIEMENT.md start "" README_DEPLOIEMENT.md
goto fin

:fin
echo.
echo Au revoir !
timeout /t 2 >nul
exit
@echo off
title Restor-PC RescueGrid - Agent
cd /d "%~dp0"

:: Vérifier si l'agent existe
if not exist "agent\windows\Invoke-RescueGrid.ps1" (
    echo [ERREUR] Agent introuvable : agent\windows\Invoke-RescueGrid.ps1
    pause
    exit /b 1
)

set CLIENT=
set ROOT=
set PROFILE=
set OFFLINE=
set ESSENTIAL=
set SKIP=

:: Demander les paramètres
echo =============================================
echo    Restor-PC RescueGrid - Agent
echo =============================================
echo.
set /p CLIENT="Nom du client : "
if "%CLIENT%"=="" (
    echo [ERREUR] Nom du client obligatoire
    pause
    exit /b 1
)

set /p ROOT="Dossier backup (defaut: E:\RestorPC) : "
if "%ROOT%"=="" set "ROOT=E:\RestorPC"

set /p PROFILE="Profil utilisateur (optionnel, Enter pour skip) : "
set /p OFFLINE="Chemin Windows offline (optionnel, Enter pour skip) : "

echo.
echo Mode essentiel (Bureau, Documents, etc.) ? (O/N)
set /p ESSENTIAL="Choix : "

echo.
echo Consentement automatique ? (O/N)
set /p SKIP="Choix : "

:: Construire la commande
set CMD=powershell -ExecutionPolicy Bypass -File "agent\windows\Invoke-RescueGrid.ps1" -ClientName "%CLIENT%" -BackupRoot "%ROOT%"

if not "%PROFILE%"=="" set "CMD=%CMD% -UserProfilePath "%PROFILE%""
if not "%OFFLINE%"=="" set "CMD=%CMD% -OfflineWindowsPath "%OFFLINE%""
if /i "%ESSENTIAL%"=="O" set "CMD=%CMD% -BackupEssentialFoldersOnly"
if /i "%SKIP%"=="O" set "CMD=%CMD% -SkipConsent"
set "CMD=%CMD% -CreateZip"

echo.
echo Lancement : %CMD%
echo.
%CMD%

echo.
echo Appuyez sur une touche pour fermer...
pause
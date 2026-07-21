@echo off
title Restor-PC RescueGrid - Agent Windows
cd /d "%~dp0.."

:MENU
cls
echo =============================================
echo    Restor-PC RescueGrid - Agent Windows
echo =============================================
echo.
echo 1. Diagnostic complet (inventaire + rapport)
echo 2. Sauvegarde utilisateur
echo 3. Analyse disque approfondie
echo 4. Generer rapport seul
echo 5. Envoyer au dashboard
echo 6. Creer ZIP intervention
echo 7. Analyse Windows hors ligne (WinPE)
echo 8. Planifier une sauvegarde automatique
echo 9. Supprimer une sauvegarde planifiee
echo 10. Quitter
echo.

set /p CHOIX="Votre choix (1-10) : "

if "%CHOIX%"=="1" goto diagnostic
if "%CHOIX%"=="2" goto backup
if "%CHOIX%"=="3" goto diskcheck
if "%CHOIX%"=="4" goto report
if "%CHOIX%"=="5" goto upload
if "%CHOIX%"=="6" goto zip
if "%CHOIX%"=="7" goto offline
if "%CHOIX%"=="8" goto schedule
if "%CHOIX%"=="9" goto unschedule
if "%CHOIX%"=="10" goto end

echo Choix invalide.
timeout /t 2 >nul
goto MENU

:diagnostic
cls
echo === Diagnostic complet ===
set /p CLIENT="Nom du client : "
set /p ROOT="Dossier de sauvegarde (ex: E:\RestorPC) : "
echo.
echo Lancement du diagnostic...
powershell -ExecutionPolicy Bypass -File "%~dp0..\agent\windows\Invoke-RescueGrid.ps1" -ClientName "%CLIENT%" -BackupRoot "%ROOT%" -CreateZip
echo.
echo Appuyez sur une touche pour revenir au menu...
pause >nul
goto MENU

:backup
cls
echo === Sauvegarde utilisateur ===
set /p CLIENT="Nom du client : "
set /p ROOT="Dossier de sauvegarde (ex: E:\RestorPC) : "
set /p PROFILE="Chemin du profil utilisateur (ex: C:\Users\Client) : "
echo.
echo Mode essentiel (Bureau, Documents, etc.) ? (O/N)
set /p ESSENTIAL="Choix : "
echo.
echo Lancement de la sauvegarde...
if /i "%ESSENTIAL%"=="O" (
    powershell -ExecutionPolicy Bypass -File "%~dp0..\agent\windows\Invoke-RescueGrid.ps1" -ClientName "%CLIENT%" -BackupRoot "%ROOT%" -UserProfilePath "%PROFILE%" -BackupEssentialFoldersOnly -CreateZip
) else (
    powershell -ExecutionPolicy Bypass -File "%~dp0..\agent\windows\Invoke-RescueGrid.ps1" -ClientName "%CLIENT%" -BackupRoot "%ROOT%" -UserProfilePath "%PROFILE%" -CreateZip
)
echo.
echo Appuyez sur une touche pour revenir au menu...
pause >nul
goto MENU

:diskcheck
cls
echo === Analyse disque ===
set /p CLIENT="Nom du client : "
set /p ROOT="Dossier de sauvegarde (ex: E:\RestorPC) : "
echo.
echo Lancement de l'analyse disque...
powershell -ExecutionPolicy Bypass -File "%~dp0..\agent\windows\Invoke-RescueGrid.ps1" -ClientName "%CLIENT%" -BackupRoot "%ROOT%" -CreateZip
echo.
echo Rapport genere. Verifier le dossier intervention.
echo Appuyez sur une touche pour revenir au menu...
pause >nul
goto MENU

:report
cls
echo === Generer rapport ===
set /p CLIENT="Nom du client : "
set /p ROOT="Dossier de sauvegarde (ex: E:\RestorPC) : "
echo.
echo Generation du rapport...
powershell -ExecutionPolicy Bypass -File "%~dp0..\agent\windows\Invoke-RescueGrid.ps1" -ClientName "%CLIENT%" -BackupRoot "%ROOT%"
echo.
echo Appuyez sur une touche pour revenir au menu...
pause >nul
goto MENU

:upload
cls
echo === Envoyer au dashboard ===
set /p CLIENT="Nom du client : "
set /p ROOT="Dossier de sauvegarde (ex: E:\RestorPC) : "
set /p URL="URL du dashboard (ex: http://localhost:8000/upload) : "
echo.
echo Envoi vers le dashboard...
powershell -ExecutionPolicy Bypass -File "%~dp0..\agent\windows\Invoke-RescueGrid.ps1" -ClientName "%CLIENT%" -BackupRoot "%ROOT%" -DashboardUploadUrl "%URL%" -CreateZip
echo.
echo Appuyez sur une touche pour revenir au menu...
pause >nul
goto MENU

:zip
cls
echo === Creer ZIP intervention ===
set /p CLIENT="Nom du client : "
set /p ROOT="Dossier de sauvegarde (ex: E:\RestorPC) : "
echo.
echo Creation du ZIP...
powershell -ExecutionPolicy Bypass -File "%~dp0..\agent\windows\Invoke-RescueGrid.ps1" -ClientName "%CLIENT%" -BackupRoot "%ROOT%" -CreateZip
echo.
echo Appuyez sur une touche pour revenir au menu...
pause >nul
goto MENU

:offline
cls
echo === Analyse Windows hors ligne ===
set /p CLIENT="Nom du client : "
set /p ROOT="Dossier de sauvegarde (ex: E:\RestorPC) : "
set /p WINDIR="Chemin Windows offline (ex: D:\Windows) : "
echo.
echo Lancement de l'analyse offline...
powershell -ExecutionPolicy Bypass -File "%~dp0..\agent\windows\Invoke-RescueGrid.ps1" -ClientName "%CLIENT%" -BackupRoot "%ROOT%" -OfflineWindowsPath "%WINDIR%" -CreateZip
echo.
echo Appuyez sur une touche pour revenir au menu...
pause >nul
goto MENU

:schedule
cls
echo === Planifier une sauvegarde automatique ===
echo ATTENTION : n?cessite une invite administrateur (elevation UAC).
echo Le consentement client initial doit avoir ete obtenu manuellement au prealable.
echo.
set /p CLIENT="Nom du client : "
set /p ROOT="Dossier de sauvegarde (ex: E:\RestorPC) : "
set /p PROFILE="Chemin du profil utilisateur (optionnel, ex: C:\Users\Client) : "
set /p URL="URL d'upload dashboard (optionnel, ex: http://192.168.1.10:8000/upload) : "
set /p APIKEY="Cle API upload (optionnelle) : "
set /p FREQ="Frequence Daily/Weekly (defaut Daily) : "
set /p HEURE="Heure HH:mm (defaut 03:00) : "
if "%FREQ%"=="" set FREQ=Daily
if "%HEURE%"=="" set HEURE=03:00
echo.
echo Installation de la tache planifiee...
set ARGS=-ClientName "%CLIENT%" -BackupRoot "%ROOT%" -Frequency %FREQ% -TimeOfDay "%HEURE%"
if not "%PROFILE%"=="" set ARGS=%ARGS% -UserProfilePath "%PROFILE%"
if not "%URL%"=="" set ARGS=%ARGS% -DashboardUploadUrl "%URL%"
if not "%APIKEY%"=="" set ARGS=%ARGS% -UploadApiKey "%APIKEY%"
powershell -ExecutionPolicy Bypass -File "%~dp0..\agent\windows\winpe\Register-RescueGridScheduledTask.ps1" %ARGS%
echo.
echo Appuyez sur une touche pour revenir au menu...
pause >nul
goto MENU

:unschedule
cls
echo === Supprimer une sauvegarde planifiee ===
set /p CLIENT="Nom du client (associe a la tache a supprimer) : "
powershell -ExecutionPolicy Bypass -File "%~dp0..\agent\windows\winpe\Register-RescueGridScheduledTask.ps1" -Unregister -ClientName "%CLIENT%"
echo.
echo Appuyez sur une touche pour revenir au menu...
pause >nul
goto MENU

:end
echo.
echo Au revoir.
timeout /t 2 >nul
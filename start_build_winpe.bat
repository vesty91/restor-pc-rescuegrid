@echo off
cd /d "%~dp0"
echo.
echo Restor-PC RescueGrid - Construction image WinPE (ADK)
echo A LANCER EN ADMINISTRATEUR (clic droit -^> Executer en tant qu'administrateur)
echo Necessite le Windows ADK + add-on WinPE installes (voir docs\TECHNICIAN_MANUAL.md).
echo.
set /p ISO="Generer aussi une ISO bootable ? (O/N, defaut N) : "
if /i "%ISO%"=="O" (
    powershell -ExecutionPolicy Bypass -File "agent\windows\Build-RescueGridWinPE.ps1" -Force -BuildIso
) else (
    powershell -ExecutionPolicy Bypass -File "agent\windows\Build-RescueGridWinPE.ps1" -Force
)
pause

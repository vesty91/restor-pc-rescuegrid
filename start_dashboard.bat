@echo off
title Restor-PC RescueGrid - Dashboard
cd /d "%~dp0"

if not exist "backend\" (
    echo [ERREUR] Dossier backend introuvable.
    pause
    exit /b 1
)

if not exist "backend\.venv\Scripts\python.exe" (
    echo [ERREUR] Environnement virtuel absent.
    echo [INFO] Lance d'abord : powershell -ExecutionPolicy Bypass -File install_dependencies.ps1
    pause
    exit /b 1
)

cd backend
call .venv\Scripts\activate.bat

if not exist "storage\" mkdir storage
if not exist "storage\uploads\" mkdir storage\uploads
if not exist "storage\reports\" mkdir storage\reports

echo [INFO] Application des migrations Alembic...
.venv\Scripts\python.exe -m alembic upgrade head
if %errorlevel% neq 0 (
    echo [ERREUR] Echec des migrations Alembic.
    pause
    exit /b 1
)

echo [OK] Demarrage du dashboard Restor-PC RescueGrid
echo [INFO] Ouvrir http://localhost:8000 dans le navigateur
echo [INFO] Ctrl+C pour arreter
echo.
.venv\Scripts\python.exe -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000

pause

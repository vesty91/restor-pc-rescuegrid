@echo off
title Restor-PC RescueGrid - Dashboard
cd /d "%~dp0"

if not exist "backend\" (
    echo [ERREUR] Dossier backend introuvable.
    pause
    exit /b 1
)

set PYTHON_CMD=
py -3.12 --version >nul 2>&1
if %errorlevel% equ 0 (
    set PYTHON_CMD=py -3.12
) else (
    py -3.11 --version >nul 2>&1
    if %errorlevel% equ 0 (
        set PYTHON_CMD=py -3.11
    ) else (
        set PYTHON_CMD=python
    )
)

if not exist "backend\.venv\" (
    echo [INFO] Creation environnement virtuel Python...
    cd backend
    %PYTHON_CMD% -m venv .venv
    if %errorlevel% neq 0 (
        echo [ERREUR] Impossible de creer le venv.
        pause
        exit /b 1
    )
    cd ..
)

echo [INFO] Installation des dependances...
cd backend
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
python -m pip install -q -r requirements.txt
if %errorlevel% neq 0 (
    echo [ERREUR] Echec installation dependances.
    pause
    exit /b 1
)

if not exist "storage\" mkdir storage
if not exist "storage\uploads\" mkdir storage\uploads
if not exist "storage\reports\" mkdir storage\reports

echo [OK] Demarrage du dashboard Restor-PC RescueGrid
echo [INFO] Ouvrir http://localhost:8000 dans le navigateur
echo [INFO] Ctrl+C pour arreter
echo.
python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

pause

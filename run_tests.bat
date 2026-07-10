@echo off
title Restor-PC RescueGrid - Tests
cd /d "%~dp0backend"

if not exist ".venv\" (
    echo [INFO] Creation environnement virtuel...
    py -3.12 -m venv .venv 2>nul
    if errorlevel 1 python -m venv .venv
)

call .venv\Scripts\activate.bat
python -m pip install -q -r requirements.txt

echo [INFO] Execution des tests d'integration...
python tests\run_tests.py
set EXIT_CODE=%errorlevel%

if %EXIT_CODE% equ 0 (
    echo.
    echo [OK] Tous les tests sont passes.
) else (
    echo.
    echo [ERREUR] Certains tests ont echoue. Code: %EXIT_CODE%
)

pause
exit /b %EXIT_CODE%

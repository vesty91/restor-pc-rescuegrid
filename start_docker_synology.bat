@echo off
title Restor-PC RescueGrid - Synology Docker
cd /d "%~dp0"

if not exist ".env" (
    echo [INFO] Creation de .env depuis .env.example
    copy ".env.example" ".env" >nul
    echo [IMPORTANT] Modifie .env avant production : SECRET_KEY, ADMIN_PASSWORD, POSTGRES_PASSWORD.
)

docker compose -f docker-compose.synology.yml up -d
if %errorlevel% neq 0 (
    echo [ERREUR] Docker compose a echoue.
    pause
    exit /b 1
)

echo [OK] Stack Synology lancee.
echo Dashboard via Nginx : http://localhost
echo Backend direct selon configuration Docker.
pause

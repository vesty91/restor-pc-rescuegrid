<#
.SYNOPSIS
    Demarre la stack Docker Synology (docker-compose.synology.yml).
#>
$ErrorActionPreference = "Stop"
$rootDir = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $rootDir

if (-not (Test-Path ".env")) {
    Write-Host "[INFO] Creation de .env depuis .env.example" -ForegroundColor Yellow
    Copy-Item ".env.example" ".env"
    Write-Host "[IMPORTANT] Modifie .env avant production : SECRET_KEY, ADMIN_PASSWORD, POSTGRES_PASSWORD." -ForegroundColor Cyan
}

docker compose -f docker-compose.synology.yml up -d
if ($LASTEXITCODE -ne 0) {
    Write-Host "[ERREUR] Docker compose a echoue." -ForegroundColor Red
    exit 1
}

Write-Host "[OK] Stack Synology lancee." -ForegroundColor Green
Write-Host "Dashboard via Nginx : http://localhost"
Write-Host "Backend direct selon configuration Docker."

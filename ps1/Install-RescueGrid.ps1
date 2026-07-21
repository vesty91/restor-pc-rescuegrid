<#
.SYNOPSIS
    Installateur 1 clic Restor-PC RescueGrid
.DESCRIPTION
    Installe les dependances Python, prepare .env, migre la BDD et lance le dashboard.
#>

$ErrorActionPreference = "Stop"
$rootDir = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $rootDir

Write-Host ""
Write-Host "=============================================" -ForegroundColor Cyan
Write-Host "  Restor-PC RescueGrid — Installation" -ForegroundColor Cyan
Write-Host "=============================================" -ForegroundColor Cyan
Write-Host ""

# 1) Dependances
$deps = Join-Path $rootDir "ps1\install_dependencies.ps1"
if (-not (Test-Path $deps)) {
    Write-Host "[ERREUR] Script introuvable : $deps" -ForegroundColor Red
    exit 1
}
Write-Host "[1/4] Dependances Python..." -ForegroundColor White
& powershell -NoProfile -ExecutionPolicy Bypass -File $deps
if ($LASTEXITCODE -ne 0) {
    Write-Host "[ERREUR] Echec install_dependencies.ps1" -ForegroundColor Red
    exit $LASTEXITCODE
}

# 2) Fichiers .env
Write-Host "[2/4] Configuration .env..." -ForegroundColor White
$rootExample = Join-Path $rootDir ".env.example"
$rootEnv = Join-Path $rootDir ".env"
$backendExample = Join-Path $rootDir "backend\.env.example"
$backendEnv = Join-Path $rootDir "backend\.env"

if (-not (Test-Path $rootEnv) -and (Test-Path $rootExample)) {
    Copy-Item $rootExample $rootEnv
    Write-Host "  -> .env cree depuis .env.example" -ForegroundColor Gray
}
elseif (Test-Path $rootEnv) {
    Write-Host "  -> .env deja present" -ForegroundColor Gray
}

if (-not (Test-Path $backendEnv)) {
    if (Test-Path $backendExample) {
        Copy-Item $backendExample $backendEnv
        Write-Host "  -> backend\.env cree depuis backend\.env.example" -ForegroundColor Gray
    }
    elseif (Test-Path $rootEnv) {
        Copy-Item $rootEnv $backendEnv
        Write-Host "  -> backend\.env cree depuis .env racine" -ForegroundColor Gray
    }
    elseif (Test-Path $rootExample) {
        Copy-Item $rootExample $backendEnv
        Write-Host "  -> backend\.env cree depuis .env.example" -ForegroundColor Gray
    }
}
else {
    Write-Host "  -> backend\.env deja present" -ForegroundColor Gray
}

# 3) Migrations Alembic
Write-Host "[3/4] Migrations Alembic..." -ForegroundColor White
$python = Join-Path $rootDir "backend\.venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    Write-Host "[ERREUR] Python venv introuvable : $python" -ForegroundColor Red
    exit 1
}
Push-Location (Join-Path $rootDir "backend")
try {
    & $python -m alembic upgrade head
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[ERREUR] alembic upgrade head a echoue" -ForegroundColor Red
        exit $LASTEXITCODE
    }
}
finally {
    Pop-Location
}
Write-Host "  -> OK" -ForegroundColor Green

# 4) Lancer le dashboard
Write-Host "[4/4] Demarrage du dashboard..." -ForegroundColor White
Write-Host ""
Write-Host "Dashboard : http://localhost:8000" -ForegroundColor Cyan
Write-Host "Page produit : http://localhost:8000/produit" -ForegroundColor Cyan
Write-Host ""

$dashBat = Join-Path $rootDir "bat\start_dashboard.bat"
if (-not (Test-Path $dashBat)) {
    Write-Host "[ERREUR] Introuvable : $dashBat" -ForegroundColor Red
    exit 1
}
& cmd /c "`"$dashBat`""

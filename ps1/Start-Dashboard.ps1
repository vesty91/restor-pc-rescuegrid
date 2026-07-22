<#
.SYNOPSIS
    Demarre le dashboard Restor-PC RescueGrid (venv + alembic + uvicorn).
#>
$ErrorActionPreference = "Stop"
try {
    [Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
    $OutputEncoding = [Console]::OutputEncoding
} catch {}

$rootDir = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$backend = Join-Path $rootDir "backend"
$py = Join-Path $backend ".venv\Scripts\python.exe"

if (-not (Test-Path $backend)) {
    Write-Host "[ERREUR] Dossier backend introuvable." -ForegroundColor Red
    exit 1
}
if (-not (Test-Path $py)) {
    Write-Host "[ERREUR] Environnement virtuel absent." -ForegroundColor Red
    Write-Host "[INFO] Lance d'abord : powershell -ExecutionPolicy Bypass -File ps1\install_dependencies.ps1"
    exit 1
}

Set-Location $backend
foreach ($d in @("storage", "storage\uploads", "storage\reports")) {
    $p = Join-Path $backend $d
    if (-not (Test-Path $p)) { New-Item -ItemType Directory -Path $p | Out-Null }
}

$env:PYTHONUTF8 = "1"
Write-Host "[INFO] Application des migrations Alembic..." -ForegroundColor White
& $py -m alembic upgrade head
if ($LASTEXITCODE -ne 0) {
    Write-Host "[ERREUR] Echec des migrations Alembic." -ForegroundColor Red
    exit 1
}

Write-Host "[OK] Demarrage du dashboard Restor-PC RescueGrid" -ForegroundColor Green
Write-Host "[INFO] Ouvrir http://localhost:8000 dans le navigateur"
Write-Host "[INFO] Ctrl+C pour arreter"
Write-Host ""
& $py -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000

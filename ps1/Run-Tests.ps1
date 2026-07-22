<#
.SYNOPSIS
    Lance la suite de tests d'integration (backend\tests\run_tests.py).
#>
$ErrorActionPreference = "Stop"
try {
    [Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
    $OutputEncoding = [Console]::OutputEncoding
} catch {}

$rootDir = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$backend = Join-Path $rootDir "backend"
$py = Join-Path $backend ".venv\Scripts\python.exe"
$env:PYTHONUTF8 = "1"

Set-Location $backend
if (-not (Test-Path $py)) {
    Write-Host "[INFO] Creation environnement virtuel..." -ForegroundColor Yellow
    $created = $false
    try {
        & py -3.12 -m venv .venv
        if ($LASTEXITCODE -eq 0) { $created = $true }
    } catch {}
    if (-not $created) {
        & python -m venv .venv
    }
    $py = Join-Path $backend ".venv\Scripts\python.exe"
}

Write-Host "[INFO] Installation / maj dependances..." -ForegroundColor White
& $py -m pip install -q -r requirements.txt

Write-Host "[INFO] Execution des tests d'integration..." -ForegroundColor White
& $py tests\run_tests.py
$code = $LASTEXITCODE
if ($code -eq 0) {
    Write-Host ""
    Write-Host "[OK] Tous les tests sont passes." -ForegroundColor Green
} else {
    Write-Host ""
    Write-Host "[ERREUR] Certains tests ont echoue. Code: $code" -ForegroundColor Red
}
exit $code

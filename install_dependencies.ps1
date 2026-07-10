<#
.SYNOPSIS
    Installer les dependances Restor-PC RescueGrid
.DESCRIPTION
    Verifie Python, cree un venv dans backend\.venv et installe les packages pip.
.NOTES
    Version : 8.1 tools
#>

$ErrorActionPreference = "Stop"
$rootDir = Split-Path -Parent $MyInvocation.MyCommand.Path

function Get-RescueGridPython {
    $candidates = @(
        @("py", "-3.12"),
        @("py", "-3.11"),
        @("python", "")
    )

    foreach ($candidate in $candidates) {
        $exe = $candidate[0]
        $arg = $candidate[1]
        try {
            if ($arg -eq "") {
                $versionText = & $exe --version 2>&1
            } else {
                $versionText = & $exe $arg --version 2>&1
            }

            if ($versionText -match "Python 3\.(1[1-9]|[2-9]\d+)") {
                return @{
                    Exe = $exe
                    Arg = $arg
                    Version = $versionText.ToString()
                }
            }
        }
        catch {
            continue
        }
    }

    throw "Python 3.11 ou 3.12 introuvable. Installe Python 3.12 avec : winget install Python.Python.3.12"
}

Write-Host "=============================================" -ForegroundColor Cyan
Write-Host "   Restor-PC RescueGrid - Installation"
Write-Host "=============================================" -ForegroundColor Cyan
Write-Host ""

# === 1. Verifier Python ===
Write-Host "[1/5] Verification de Python..." -NoNewline
$py = Get-RescueGridPython
Write-Host " $($py.Version)" -ForegroundColor Green

# === 2. Creer environnement virtuel ===
Write-Host "[2/5] Environnement virtuel Python..." -NoNewline
$backendDir = Join-Path $rootDir "backend"
$venvPath = Join-Path $backendDir ".venv"

if (-not (Test-Path $backendDir)) {
    throw "Dossier backend introuvable : $backendDir"
}

if (-not (Test-Path $venvPath)) {
    Push-Location $backendDir
    try {
        if ($py.Arg -eq "") {
            & $py.Exe -m venv .venv
        } else {
            & $py.Exe $py.Arg -m venv .venv
        }
        Write-Host " CREE" -ForegroundColor Green
    }
    finally {
        Pop-Location
    }
}
else {
    Write-Host " DEJA EXISTANT" -ForegroundColor Green
}

# === 3. Installer les dependances pip ===
Write-Host "[3/5] Installation des packages Python..." -NoNewline
$pipPath = Join-Path $venvPath "Scripts\pip.exe"
$pythonVenvPath = Join-Path $venvPath "Scripts\python.exe"
$requirementsPath = Join-Path $backendDir "requirements.txt"

if ((Test-Path $pythonVenvPath) -and (Test-Path $requirementsPath)) {
    try {
        & $pythonVenvPath -m pip install --upgrade pip | Out-Null
        & $pythonVenvPath -m pip install -q -r $requirementsPath
        Write-Host " OK" -ForegroundColor Green
    }
    catch {
        Write-Host " ECHEC" -ForegroundColor Red
        Write-Host "  -> $($_.Exception.Message)"
        exit 1
    }
}
else {
    Write-Host " ECHEC" -ForegroundColor Red
    Write-Host "  -> Fichier introuvable : $pythonVenvPath ou $requirementsPath"
    exit 1
}

# === 4. Verifier les scripts .bat ===
Write-Host "[4/5] Verification des scripts .bat..." -NoNewline
$batFiles = @(
    "start_dashboard.bat",
    "start_agent.bat",
    "start_agent_windows.bat",
    "start_winpe_menu.bat"
)
$missing = $batFiles | Where-Object { -not (Test-Path (Join-Path $rootDir $_)) }
if ($missing.Count -eq 0) {
    Write-Host " OK ($($batFiles.Count) fichiers)" -ForegroundColor Green
}
else {
    Write-Host " MANQUANTS : $($missing -join ', ')" -ForegroundColor Yellow
}

# === 5. Creer dossiers storage ===
Write-Host "[5/5] Dossiers de stockage..." -NoNewline
$storageDirs = @(
    "storage",
    "storage\uploads",
    "storage\reports"
)
foreach ($dir in $storageDirs) {
    $fullPath = Join-Path $rootDir $dir
    if (-not (Test-Path $fullPath)) {
        New-Item -ItemType Directory -Path $fullPath -Force | Out-Null
    }
}
Write-Host " OK" -ForegroundColor Green

Write-Host ""
Write-Host "=============================================" -ForegroundColor Cyan
Write-Host "   INSTALLATION TERMINEE" -ForegroundColor Green
Write-Host "=============================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Commandes disponibles :" -ForegroundColor White
Write-Host "  .\start_dashboard.bat     -> Lancer le dashboard" -ForegroundColor Gray
Write-Host "  .\start_agent.bat         -> Lancer l'agent Windows" -ForegroundColor Gray
Write-Host "  .\start_agent_windows.bat -> Menu technicien" -ForegroundColor Gray
Write-Host "  .\start_winpe_menu.bat    -> Menu WinPE" -ForegroundColor Gray
Write-Host "  .\start_tools_install.bat -> Installer smartctl / CrystalDiskInfo" -ForegroundColor Gray
Write-Host ""
Write-Host "Dashboard : http://localhost:8000" -ForegroundColor Cyan
Write-Host ""

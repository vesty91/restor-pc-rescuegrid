<#
.SYNOPSIS
    Installer les dependances Restor-PC RescueGrid
.DESCRIPTION
    Verifie Python, cree un venv dans backend\.venv et installe les packages pip.
.NOTES
    Version : 12.5.2
#>

$ErrorActionPreference = "Stop"
try {
    [Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
    $OutputEncoding = [Console]::OutputEncoding
} catch {}
$rootDir = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)

# Python 3.12 uniquement (image Docker = python:3.12-slim-bookworm). Un simple
# "python" du PATH peut pointer vers 3.11/3.13/3.14 : on vérifie la version
# réelle, pas seulement l'existence de la commande.
function Test-RescueGridPythonVersion {
    param([string]$VersionText)
    return $VersionText -match "^Python 3\.12(\.|$)"
}

function Get-RescueGridPython {
    $candidates = @(
        @("py", "-3.12"),
        @("python", "")
    )

    foreach ($candidate in $candidates) {
        $exe = $candidate[0]
        $arg = $candidate[1]
        try {
            if ($arg -eq "") {
                $versionText = (& $exe --version 2>&1).ToString().Trim()
            } else {
                $versionText = (& $exe $arg --version 2>&1).ToString().Trim()
            }

            if (Test-RescueGridPythonVersion $versionText) {
                return @{
                    Exe = $exe
                    Arg = $arg
                    Version = $versionText
                }
            }
        }
        catch {
            continue
        }
    }

    throw "Python 3.12 introuvable (seule version supportée). Installe-le avec : winget install Python.Python.3.12"
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

$venvPythonExe = Join-Path $venvPath "Scripts\python.exe"

if ((Test-Path $venvPath) -and (Test-Path $venvPythonExe)) {
    # Le .venv existe déjà : vérifie qu'il a bien été créé avec Python 3.12
    # et pas une autre version (3.11/3.13/3.14 devenue le "python" par défaut
    # du PATH) — sinon les dépendances compilées (psycopg, cryptography...)
    # peuvent échouer à l'installation ou au runtime de façon peu explicite.
    $venvVersionText = (& $venvPythonExe --version 2>&1).ToString().Trim()
    if (-not (Test-RescueGridPythonVersion $venvVersionText)) {
        Write-Host " INCOMPATIBLE ($venvVersionText) -> recreation..." -ForegroundColor Yellow
        Remove-Item -Path $venvPath -Recurse -Force
    }
}

if (-not (Test-Path $venvPath)) {
    Push-Location $backendDir
    try {
        if ($py.Arg -eq "") {
            & $py.Exe -m venv .venv
        } else {
            & $py.Exe $py.Arg -m venv .venv
        }
        Write-Host " CREE ($($py.Version))" -ForegroundColor Green
    }
    finally {
        Pop-Location
    }
}
else {
    Write-Host " DEJA EXISTANT ($venvVersionText)" -ForegroundColor Green
}

# === 3. Installer les dependances pip ===
Write-Host "[3/5] Installation des packages Python..." -NoNewline
$pipPath = Join-Path $venvPath "Scripts\pip.exe"
$pythonVenvPath = Join-Path $venvPath "Scripts\python.exe"
$requirementsPath = Join-Path $backendDir "requirements.txt"

if ((Test-Path $pythonVenvPath) -and (Test-Path $requirementsPath)) {
    try {
        # PowerShell n'élève pas automatiquement un exit code pip non nul :
        # sans contrôle de $LASTEXITCODE, le script affichait "OK" après un échec.
        & $pythonVenvPath -m pip install --upgrade pip | Out-Null
        if ($LASTEXITCODE -ne 0) {
            throw "Echec de la mise a jour de pip (code $LASTEXITCODE)."
        }
        & $pythonVenvPath -m pip install -q -r $requirementsPath
        if ($LASTEXITCODE -ne 0) {
            throw "Echec de l'installation des dependances (code $LASTEXITCODE)."
        }
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
    "bat\start_dashboard.bat",
    "bat\start_agent.bat",
    "bat\start_agent_windows.bat",
    "bat\start_tools_install.bat"
)
$missing = $batFiles | Where-Object { -not (Test-Path (Join-Path $rootDir $_)) }
if ($missing.Count -eq 0) {
    Write-Host " OK ($($batFiles.Count) fichiers)" -ForegroundColor Green
}
else {
    Write-Host " MANQUANTS : $($missing -join ', ')" -ForegroundColor Yellow
}

# === 5. Creer dossiers storage (chemin utilise par l'app : backend/storage) ===
Write-Host "[5/5] Dossiers de stockage..." -NoNewline
$storageDirs = @(
    "storage",
    "storage\uploads",
    "storage\reports"
)
foreach ($dir in $storageDirs) {
    $fullPath = Join-Path $backendDir $dir
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
Write-Host "  .\bat\start_dashboard.bat     -> Lancer le dashboard" -ForegroundColor Gray
Write-Host "  .\bat\start_agent.bat         -> Lancer l'agent Windows" -ForegroundColor Gray
Write-Host "  .\bat\start_agent_windows.bat -> Menu technicien" -ForegroundColor Gray
Write-Host "  .\bat\Apply-WinPE-WinXShell.bat -> Injecter bureau WinPE" -ForegroundColor Gray
Write-Host "  .\bat\start_tools_install.bat -> Installer smartctl / CrystalDiskInfo" -ForegroundColor Gray
Write-Host "  .\ps1\install_dependencies.ps1 -> Installer deps Python" -ForegroundColor Gray
Write-Host ""
Write-Host "Dashboard : http://localhost:8000" -ForegroundColor Cyan
Write-Host ""


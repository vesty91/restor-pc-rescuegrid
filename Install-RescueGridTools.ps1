# Restor-PC RescueGrid - Optional tools installer
# Installe les outils SMART/Récupération nécessaires si absents.
# Exécuter en PowerShell administrateur recommandé.

$ErrorActionPreference = "Continue"

function Write-Ok($m){ Write-Host "[OK] $m" -ForegroundColor Green }
function Write-Info($m){ Write-Host "[INFO] $m" -ForegroundColor Cyan }
function Write-Warn($m){ Write-Host "[WARN] $m" -ForegroundColor Yellow }
function Write-Bad($m){ Write-Host "[ERR] $m" -ForegroundColor Red }

function Has-Command($name) {
    return $null -ne (Get-Command $name -ErrorAction SilentlyContinue)
}

Write-Host "=============================================" -ForegroundColor Cyan
Write-Host " Restor-PC RescueGrid - Outils SMART" -ForegroundColor White
Write-Host "=============================================" -ForegroundColor Cyan

$toolsRoot = Join-Path $PSScriptRoot "tools"
$smartmontoolsPortable = Join-Path $toolsRoot "smartmontools\bin\smartctl.exe"
$crystalPortable64 = Join-Path $toolsRoot "CrystalDiskInfo\DiskInfo64.exe"
$crystalPortable32 = Join-Path $toolsRoot "CrystalDiskInfo\DiskInfo32.exe"

New-Item -ItemType Directory -Force -Path $toolsRoot | Out-Null

# smartmontools
$smartctl = Get-Command smartctl -ErrorAction SilentlyContinue
if ($smartctl) {
    Write-Ok "smartctl detecte : $($smartctl.Source)"
}
elseif (Test-Path $smartmontoolsPortable) {
    Write-Ok "smartctl portable detecte : $smartmontoolsPortable"
}
else {
    Write-Warn "smartctl absent."
    if (Has-Command winget) {
        Write-Info "Installation smartmontools via winget..."
        winget install --id smartmontools.smartmontools --accept-source-agreements --accept-package-agreements
        $smartctl = Get-Command smartctl -ErrorAction SilentlyContinue
        if ($smartctl) { Write-Ok "smartctl installe : $($smartctl.Source)" } else { Write-Warn "smartctl non visible dans le PATH. Redemarre PowerShell ou le PC." }
    }
    else {
        Write-Warn "winget indisponible. Installe smartmontools manuellement ou place smartctl.exe dans tools\smartmontools\bin\."
    }
}

# CrystalDiskInfo
$crystal = Get-Command DiskInfo64.exe -ErrorAction SilentlyContinue
if ($crystal) {
    Write-Ok "CrystalDiskInfo CLI detecte : $($crystal.Source)"
}
elseif ((Test-Path $crystalPortable64) -or (Test-Path $crystalPortable32)) {
    Write-Ok "CrystalDiskInfo portable detecte dans tools\CrystalDiskInfo"
}
else {
    Write-Warn "CrystalDiskInfo absent."
    if (Has-Command winget) {
        Write-Info "Installation CrystalDiskInfo via winget..."
        winget install --id CrystalDewWorld.CrystalDiskInfo --accept-source-agreements --accept-package-agreements
        Write-Info "Si DiskInfo64.exe n'est pas dans le PATH, l'agent cherchera aussi dans Program Files."
    }
    else {
        Write-Warn "winget indisponible. Place DiskInfo64.exe dans tools\CrystalDiskInfo\."
    }
}

Write-Host ""
Write-Info "Test smartctl --scan :"
$smartctlCmd = (Get-Command smartctl -ErrorAction SilentlyContinue).Source
if (-not $smartctlCmd -and (Test-Path $smartmontoolsPortable)) { $smartctlCmd = $smartmontoolsPortable }
if ($smartctlCmd) {
    & $smartctlCmd --scan 2>&1
}
else {
    Write-Warn "smartctl toujours indisponible."
}

Write-Host ""
Write-Ok "Verification terminee."
Write-Host "Relance ensuite l'agent RescueGrid pour remplir les temperatures SMART."
Pause

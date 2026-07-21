<#
.SYNOPSIS
  Pack USB Restor-PC prêt à l'emploi (orchestrateur).

.DESCRIPTION
  Enchaine :
  1. Create-RescueGridUSB.ps1 (structure + agent + config)
  2. Si boot.wim present sur la cle → Apply-WinPE-WinXShell.ps1
     Sinon avec -MakeBootable → Flash-RescueGridWinPE-USB.ps1 (EFFACE la cle, ADK requis)
  3. Copie Lockpick\ → RescueGrid\Lockpick\ si present
  4. Copie tools\ projet → RescueGrid\tools\ si present
  5. Ecrit PACK_USB_README.txt sur la cle

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File agent\windows\winpe\Build-ReadyUSB.ps1 -TargetDrive E: -DashboardUrl "http://192.168.1.10:8000"

.EXAMPLE
  # Cle deja bootable (boot.wim) : injecte WinXShell sans reformater
  powershell -ExecutionPolicy Bypass -File agent\windows\winpe\Build-ReadyUSB.ps1 -TargetDrive E:

.EXAMPLE
  # Rendre bootable (ADK) — EFFACE la cle
  powershell -ExecutionPolicy Bypass -File agent\windows\winpe\Build-ReadyUSB.ps1 -TargetDrive E: -MakeBootable
#>
param(
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[A-Za-z]:$')]
    [string]$TargetDrive,

    [string]$DashboardUrl = "http://localhost:8000",

    [string]$UploadApiKey = "",

    [switch]$IncludeProject,

    [switch]$MakeBootable,

    [switch]$SkipWinXShell
)

$ErrorActionPreference = "Stop"
$scriptDir = $PSScriptRoot
$agentRoot = Resolve-Path (Join-Path $scriptDir "..") | Select-Object -ExpandProperty Path
$projectRoot = Resolve-Path (Join-Path $scriptDir "..\..\..") | Select-Object -ExpandProperty Path
$driveRoot = $TargetDrive.TrimEnd(":") + ":"

function Test-Admin {
    $p = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
    return $p.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

Write-Host ""
Write-Host "=============================================" -ForegroundColor Cyan
Write-Host "  Restor-PC — Pack USB pret a l'emploi" -ForegroundColor Cyan
Write-Host "=============================================" -ForegroundColor Cyan
Write-Host "Cle : $driveRoot"
Write-Host "Dashboard : $DashboardUrl"
Write-Host ""

if (-not (Test-Path "$driveRoot\")) {
    throw "Lecteur introuvable : $driveRoot"
}

# --- 1) Structure RescueGrid ---
Write-Host "[1/5] Create-RescueGridUSB..." -ForegroundColor White
$createParams = @{
    TargetDrive  = $driveRoot
    DashboardUrl = $DashboardUrl
}
if ($UploadApiKey) { $createParams.UploadApiKey = $UploadApiKey }
if ($IncludeProject) { $createParams.IncludeProject = $true }

& (Join-Path $scriptDir "Create-RescueGridUSB.ps1") @createParams
if ($LASTEXITCODE -and $LASTEXITCODE -ne 0) {
    throw "Create-RescueGridUSB a echoue (code $LASTEXITCODE)."
}

# --- 2) Boot / WinXShell ---
$bootWim = Join-Path $driveRoot "sources\boot.wim"
$applyScript = Join-Path $scriptDir "Apply-WinPE-WinXShell.ps1"
$flashScript = Join-Path $scriptDir "Flash-RescueGridWinPE-USB.ps1"

if ($MakeBootable) {
    if (-not (Test-Admin)) {
        throw " -MakeBootable necessite une invite Administrateur."
    }
    Write-Host "[2/5] Flash WinPE (EFFACE la cle)..." -ForegroundColor Yellow
    & $flashScript -TargetDrive $driveRoot -DashboardUrl $DashboardUrl -UploadApiKey $UploadApiKey -SkipBuild:$false
    if (-not $SkipWinXShell -and (Test-Path $bootWim) -and (Test-Path $applyScript)) {
        Write-Host "  Injection WinXShell..." -ForegroundColor Gray
        & $applyScript -BootWim $bootWim
    }
}
elseif ((Test-Path $bootWim) -and -not $SkipWinXShell) {
    Write-Host "[2/5] boot.wim detecte — injection WinXShell..." -ForegroundColor White
    if (-not (Test-Admin)) {
        Write-Host "  [WARN] Admin requis pour monter boot.wim — sautez ou relancez en admin." -ForegroundColor Yellow
    }
    else {
        & $applyScript -BootWim $bootWim
    }
}
else {
    Write-Host "[2/5] Pas de boot.wim sur la cle." -ForegroundColor Yellow
    Write-Host "  Pour une cle bootable : -MakeBootable (ADK + WinPE) ou copiez sources\boot.wim puis relancez." -ForegroundColor Gray
}

# --- 3) Lockpick / Unlocker (optionnel, hors dépôt GitHub public) ---
Write-Host "[3/5] Lockpick / Unlocker..." -ForegroundColor White
$lockSrc = Join-Path $projectRoot "Lockpick"
$lockDst = Join-Path $driveRoot "RescueGrid\Lockpick"
# Présent si des binaires/scripts existent au-delà du seul README.md
$lockFiles = @(Get-ChildItem -Path $lockSrc -Recurse -File -ErrorAction SilentlyContinue |
    Where-Object { $_.Name -ne "README.md" })
if ((Test-Path $lockSrc) -and $lockFiles.Count -gt 0) {
    New-Item -ItemType Directory -Force -Path $lockDst | Out-Null
    robocopy $lockSrc $lockDst /E /NFL /NDL /NJH /NJS /nc /ns /np | Out-Null
    Write-Host "  -> copie vers RescueGrid\Lockpick" -ForegroundColor Green
}
else {
    Write-Host "  -> Lockpick absent en local (voir Lockpick\README.md) — ignore" -ForegroundColor Gray
}

# --- 4) Outils ---
Write-Host "[4/5] Outils (tools\)..." -ForegroundColor White
$toolsSrc = Join-Path $projectRoot "tools"
$toolsDst = Join-Path $driveRoot "RescueGrid\tools"
if ((Test-Path $toolsSrc) -and (Get-ChildItem $toolsSrc -Recurse -File -ErrorAction SilentlyContinue | Select-Object -First 1)) {
    New-Item -ItemType Directory -Force -Path $toolsDst | Out-Null
    robocopy $toolsSrc $toolsDst /E /NFL /NDL /NJH /NJS /nc /ns /np | Out-Null
    Write-Host "  -> outils copies" -ForegroundColor Green
}
else {
    Write-Host "  -> tools\ vide — lancez ps1\Install-RescueGridTools.ps1 puis relancez ce pack." -ForegroundColor Yellow
}

# --- 5) README pack ---
Write-Host "[5/5] PACK_USB_README.txt..." -ForegroundColor White
$readme = @"
Restor-PC RescueGrid — Pack USB
================================
Dashboard : $DashboardUrl
Genere : $(Get-Date -Format "yyyy-MM-dd HH:mm")

Demarrage PC client
-------------------
1. Boot USB (F12 / menu boot fabricant).
2. Bureau WinXShell si boot.wim + Apply-WinPE-WinXShell ont ete appliques.
3. Lancer RescueGrid depuis le bureau ou Start-RescueGrid.cmd.

Sous Windows (PC technicien)
----------------------------
Double-clic Start-RescueGrid.cmd a la racine de la cle.

Unlocker
--------
RescueGrid\Lockpick\Unlocker.cmd (menu 64-bit).

Si la cle ne boot pas
---------------------
Installer Windows ADK + WinPE Addon, puis :
  bat\Build-ReadyUSB.bat  (avec -MakeBootable)
ou
  agent\windows\winpe\Flash-RescueGridWinPE-USB.ps1

Doc : docs\TECHNICIAN_MANUAL.md
"@
Set-Content -Path (Join-Path $driveRoot "PACK_USB_README.txt") -Value $readme -Encoding UTF8

Write-Host ""
Write-Host "Pack USB termine sur $driveRoot" -ForegroundColor Green
Write-Host "Lire : $driveRoot\PACK_USB_README.txt" -ForegroundColor Cyan
Write-Host ""

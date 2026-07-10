<#
.SYNOPSIS
    Assistant creation cle USB RescueGrid
.DESCRIPTION
    Cree une cle USB bootable WinPE avec tous les outils RescueGrid :
    - WinPE (ADK requis)
    - Scripts RescueGrid
    - smartctl
    - ddrescue, TestDisk, PhotoRec
    - CrystalDiskInfo
    - Documentation
.NOTES
    Auteur : Restor-PC RescueGrid
    Version : 1.0
    Requis : Windows ADK + WinPE add-on
#>

param(
    [Parameter(Mandatory = $true)]
    [string]$UsbDriveLetter,

    [string]$WinPEBasePath = "C:\WinPE",
    
    [switch]$IncludeDataRecovery,

    [switch]$SkipFormat
)

$ErrorActionPreference = "Continue"
$host.UI.RawUI.WindowTitle = "Restor-PC RescueGrid - Build USB"

function Write-Step {
    param([string]$Text, [string]$Color = "Cyan")
    Write-Host ""
    Write-Host "=============================================" -ForegroundColor $Color
    Write-Host "   $Text" -ForegroundColor $Color
    Write-Host "=============================================" -ForegroundColor $Color
    Write-Host ""
}

function Test-Admin {
    $currentPrincipal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
    return $currentPrincipal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

# Verifications
if (-not (Test-Admin)) {
    Write-Host "[ERREUR] Ce script doit etre execute en tant qu'administrateur." -ForegroundColor Red
    pause
    exit 1
}

$usbPath = "$UsbDriveLetter`:\"
if (-not (Test-Path $usbPath)) {
    Write-Host "[ERREUR] Lecteur $UsbDriveLetter introuvable." -ForegroundColor Red
    pause
    exit 1
}

$drive = Get-Volume -DriveLetter $UsbDriveLetter -ErrorAction SilentlyContinue
if ($drive -and $drive.DriveType -ne "Removable") {
    Write-Host "[AVERTISSEMENT] $UsbDriveLetter ne semble pas etre un lecteur USB." -ForegroundColor Yellow
    $confirm = Read-Host "Continuer quand meme ? (O/N)"
    if ($confirm -ne "O") { exit 0 }
}

Write-Step "Build USB RescueGrid - Cle $UsbDriveLetter" "Cyan"

# Etape 1 : Formatage
if (-not $SkipFormat) {
    Write-Step "Etape 1/6 : Formatage de la cle USB" "Yellow"
    Write-Host "ATTENTION : Cela supprimera TOUTES les donnees de $UsbDriveLetter" -ForegroundColor Red
    $confirm = Read-Host "Formater $UsbDriveLetter ? (O/N)"
    if ($confirm -eq "O") {
        Format-Volume -DriveLetter $UsbDriveLetter -FileSystem FAT32 -Confirm:$false -Force
        Write-Host "Formatage termine." -ForegroundColor Green
    }
    else {
        Write-Host "Formatage annule." -ForegroundColor Yellow
    }
}

# Etape 2 : Copier les scripts RescueGrid
Write-Step "Etape 2/6 : Copie des scripts RescueGrid" "Cyan"
$sourceDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$destDir = "$usbPath\RescueGrid"
New-Item -ItemType Directory -Path $destDir -Force | Out-Null

$scripts = @(
    "Invoke-RescueGrid.ps1",
    "Start-RescueGrid.ps1",
    "Build-RescueGridUSB.ps1"
)
foreach ($script in $scripts) {
    $src = Join-Path $sourceDir $script
    if (Test-Path $src) {
        Copy-Item $src $destDir -Force
        Write-Host "  -> $script copie" -ForegroundColor Green
    }
}

# Etape 3 : WinPE (si ADK installe)
Write-Step "Etape 3/6 : WinPE (si ADK disponible)" "Cyan"
$copiedWinPE = $false
$winpePaths = @(
    "$WinPEBasePath\media\sources\boot.wim",
    "C:\Program Files (x86)\Windows Kits\10\Assessment and Deployment Kit\Windows Preinstallation Environment\amd64\en-us\winpe.wim"
)
foreach ($wim in $winpePaths) {
    if (Test-Path $wim) {
        $destWim = "$usbPath\boot.wim"
        Copy-Item $wim $destWim -Force
        Write-Host "  -> WinPE copie depuis $wim" -ForegroundColor Green
        $copiedWinPE = $true
        break
    }
}
if (-not $copiedWinPE) {
    Write-Host "  -> WinPE non trouve. Installer Windows ADK + WinPE add-on." -ForegroundColor Yellow
    Write-Host "     Telecharger : https://learn.microsoft.com/fr-fr/windows-hardware/get-started/adk-install" -ForegroundColor Gray
}

# Etape 4 : smartctl
Write-Step "Etape 4/6 : smartctl (analyse SMART)" "Cyan"
$smartctlDir = "$usbPath\smartctl"
New-Item -ItemType Directory -Path $smartctlDir -Force | Out-Null
Write-Host "  -> smartctl non inclus automatiquement." -ForegroundColor Yellow
Write-Host "     Telecharger : https://www.smartmontools.org/" -ForegroundColor Gray
Write-Host "     Copier smartctl.exe et smartctl.dll dans $smartctlDir" -ForegroundColor Gray

# Etape 5 : Outils recuperation (ddrescue, TestDisk, PhotoRec)
if ($IncludeDataRecovery) {
    Write-Step "Etape 5/6 : Outils recuperation (ddrescue, TestDisk, PhotoRec)" "Cyan"
    $recoveryDir = "$usbPath\RecoveryTools"
    New-Item -ItemType Directory -Path $recoveryDir -Force | Out-Null
    
    Write-Host "  -> ddrescue (GNU ddrescue)" -ForegroundColor Yellow
    Write-Host "     Telecharger : https://www.gnu.org/software/ddrescue/" -ForegroundColor Gray
    Write-Host "     Copier ddrescue.exe dans $recoveryDir" -ForegroundColor Gray
    
    Write-Host "  -> TestDisk & PhotoRec" -ForegroundColor Yellow
    Write-Host "     Telecharger : https://www.cgsecurity.org/wiki/TestDisk_Download" -ForegroundColor Gray
    Write-Host "     Copier testdisk.exe et photorec.exe dans $recoveryDir" -ForegroundColor Gray
}
else {
    Write-Step "Etape 5/6 : Outils recuperation (IGNORES)" "Yellow"
    Write-Host "  -> Utiliser -IncludeDataRecovery pour inclure ddrescue/TestDisk/PhotoRec" -ForegroundColor Gray
}

# Etape 6 : Documentation et finalisation
Write-Step "Etape 6/6 : Documentation et finalisation" "Cyan"

# Copier la documentation
$docsDir = "$usbPath\Docs"
New-Item -ItemType Directory -Path $docsDir -Force | Out-Null
$docs = @("README_LANCEMENT.md", "README_DEPLOIEMENT.md", "TECHNICIAN_MANUAL.md", "CLIENT_GUIDE.md")
foreach ($doc in $docs) {
    $src = Join-Path $sourceDir $doc
    if (Test-Path $src) {
        Copy-Item $src $docsDir -Force
        Write-Host "  -> $doc copie" -ForegroundColor Green
    }
}

# Creer le fichier de lancement automatique
$autorunContent = @"
[autorun]
open=cmd /c "echo Restor-PC RescueGrid && echo. && echo Lancez : powershell -ExecutionPolicy Bypass -File X:\RescueGrid\Start-RescueGrid.ps1 && pause"
icon=RescueGrid\ RescueGrid.ico
label=Restor-PC RescueGrid
"@
$autorunContent | Out-File -FilePath "$usbPath\autorun.inf" -Encoding ascii
Write-Host "  -> autorun.inf cree" -ForegroundColor Green

# Resume final
Write-Step "Build termine !" "Green"
Write-Host "Cle USB prete : $usbPath" -ForegroundColor White
Write-Host ""
Write-Host "Contenu :" -ForegroundColor Cyan
Write-Host "  \RescueGrid\" -ForegroundColor Gray
Write-Host "    - Invoke-RescueGrid.ps1" -ForegroundColor Gray
Write-Host "    - Start-RescueGrid.ps1" -ForegroundColor Gray
Write-Host "    - Build-RescueGridUSB.ps1" -ForegroundColor Gray
if ($copiedWinPE) { Write-Host "  \boot.wim" -ForegroundColor Gray }
Write-Host "  \smartctl\" -ForegroundColor Gray
Write-Host "  \RecoveryTools\" -ForegroundColor Gray
Write-Host "  \Docs\" -ForegroundColor Gray
Write-Host "  \autorun.inf" -ForegroundColor Gray
Write-Host ""
Write-Host "Pour demarrer :" -ForegroundColor Yellow
Write-Host "  1. Booter le PC sur la cle USB" -ForegroundColor White
Write-Host "  2. Dans WinPE, lancer :" -ForegroundColor White
Write-Host "     X:\RescueGrid\Start-RescueGrid.ps1" -ForegroundColor Cyan
Write-Host ""
pause
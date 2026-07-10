<# 
.SYNOPSIS
  Crée une clé USB technicien Restor-PC RescueGrid.

.DESCRIPTION
  Ce script prépare une clé USB de travail avec :
  - scripts PowerShell agent + menu WinPE ;
  - structure de dossiers rapports/backup/outils ;
  - fichier de configuration Dashboard/NAS ;
  - lanceur Start-RescueGrid.cmd ;
  - script startnet.cmd compatible WinPE.

  Sécurité :
  - ne formate jamais la clé sans -Format ;
  - demande confirmation avant formatage ;
  - peut copier le projet complet avec -IncludeProject.

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File agent\windows\Create-RescueGridUSB.ps1 -TargetDrive E: -DashboardUrl "http://192.168.1.10:8000" -IncludeProject

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File agent\windows\Create-RescueGridUSB.ps1 -TargetDrive E: -Format
#>

[CmdletBinding(SupportsShouldProcess=$true)]
param(
    [Parameter(Mandatory=$true)]
    [ValidatePattern('^[A-Za-z]:$')]
    [string]$TargetDrive,

    [string]$DashboardUrl = "http://localhost:8000",

    [switch]$IncludeProject,

    [switch]$Format,

    [string]$VolumeLabel = "RESCUEGRID",

    [string]$SmartctlSource = "",

    [string]$TestDiskSource = ""
)

$ErrorActionPreference = "Stop"

function Write-Step {
    param([string]$Message)
    Write-Host ""
    Write-Host "==> $Message" -ForegroundColor Cyan
}

function Copy-IfExists {
    param([string]$Source, [string]$Destination)
    if ([string]::IsNullOrWhiteSpace($Source)) { return }
    if (Test-Path $Source) {
        New-Item -ItemType Directory -Force -Path $Destination | Out-Null
        Copy-Item -Path (Join-Path $Source "*") -Destination $Destination -Recurse -Force
        Write-Host "Copié : $Source -> $Destination" -ForegroundColor Green
    } else {
        Write-Host "Source introuvable : $Source" -ForegroundColor Yellow
    }
}

$driveRoot = "$TargetDrive\"
if (-not (Test-Path $driveRoot)) {
    throw "Lecteur introuvable : $TargetDrive"
}

if ($Format) {
    Write-Host "ATTENTION : formatage demandé pour $TargetDrive" -ForegroundColor Red
    $confirm = Read-Host "Tape FORMAT pour confirmer"
    if ($confirm -ne "FORMAT") {
        throw "Formatage annulé."
    }

    Write-Step "Formatage de la clé USB"
    $partition = Get-Partition -DriveLetter $TargetDrive.TrimEnd(":") -ErrorAction SilentlyContinue | Select-Object -First 1
    if (-not $partition) { throw "Partition introuvable pour $TargetDrive" }
    Format-Volume -Partition $partition -FileSystem NTFS -NewFileSystemLabel $VolumeLabel -Confirm:$false -Force
}

Write-Step "Préparation de la structure USB"
$usbRoot = Join-Path $driveRoot "RescueGrid"
$paths = @(
    $usbRoot,
    "$usbRoot\agent\windows",
    "$usbRoot\config",
    "$usbRoot\reports",
    "$usbRoot\backup",
    "$usbRoot\blackbox",
    "$usbRoot\tools\smartctl",
    "$usbRoot\tools\testdisk",
    "$usbRoot\tools\photorec",
    "$usbRoot\winpe"
)
foreach ($p in $paths) { New-Item -ItemType Directory -Force -Path $p | Out-Null }

$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectRoot = Resolve-Path (Join-Path $scriptRoot "..\..") | Select-Object -ExpandProperty Path

Write-Step "Copie des scripts agent"
$agentFiles = @("Invoke-RescueGrid.ps1", "Start-RescueGrid.ps1")
foreach ($file in $agentFiles) {
    $src = Join-Path $scriptRoot $file
    if (Test-Path $src) {
        Copy-Item $src -Destination "$usbRoot\agent\windows\$file" -Force
        Write-Host "OK $file" -ForegroundColor Green
    } else {
        Write-Host "Manquant : $file" -ForegroundColor Yellow
    }
}

if ($IncludeProject) {
    Write-Step "Copie du projet complet sans fichiers lourds"
    $destination = Join-Path $usbRoot "project"
    New-Item -ItemType Directory -Force -Path $destination | Out-Null
    robocopy $projectRoot $destination /E /XD ".git" ".venv" "__pycache__" "storage" /XF "*.db" "*.sqlite" "*.pyc" | Out-Null
}

Copy-IfExists -Source $SmartctlSource -Destination "$usbRoot\tools\smartctl"
Copy-IfExists -Source $TestDiskSource -Destination "$usbRoot\tools\testdisk"

Write-Step "Création configuration"
$config = @"
RESCUEGRID_DASHBOARD_URL=$DashboardUrl
RESCUEGRID_USB_ROOT=$usbRoot
RESCUEGRID_BACKUP_ROOT=$usbRoot\backup
RESCUEGRID_REPORT_ROOT=$usbRoot\reports
"@
Set-Content -Path "$usbRoot\config\rescuegrid.env" -Value $config -Encoding UTF8

Write-Step "Création lanceurs"
$cmd = @"
@echo off
title Restor-PC RescueGrid USB
set RESCUEGRID_USB=%~dp0RescueGrid
powershell -NoProfile -ExecutionPolicy Bypass -File "%RESCUEGRID_USB%\agent\windows\Start-RescueGrid.ps1"
pause
"@
Set-Content -Path (Join-Path $driveRoot "Start-RescueGrid.cmd") -Value $cmd -Encoding ASCII

$startnet = @"
wpeinit
cd /d X:\
for %%D in (C D E F G H I J K L M N O P Q R S T U V W Y Z) do (
  if exist %%D:\RescueGrid\agent\windows\Start-RescueGrid.ps1 (
    powershell -NoProfile -ExecutionPolicy Bypass -File %%D:\RescueGrid\agent\windows\Start-RescueGrid.ps1
  )
)
cmd
"@
Set-Content -Path "$usbRoot\winpe\startnet.cmd" -Value $startnet -Encoding ASCII

$readme = @"
Restor-PC RescueGrid USB

Utilisation Windows :
1. Ouvrir la clé USB
2. Lancer Start-RescueGrid.cmd en administrateur

Utilisation WinPE :
1. Intégrer RescueGrid\winpe\startnet.cmd dans l'image WinPE
2. Copier le dossier RescueGrid à la racine de la clé
3. Démarrer le PC client sur la clé

Dashboard :
$DashboardUrl

Important :
- Ne lance pas de réparation disque avant sauvegarde/image si SMART est critique.
- Conserve les dossiers reports, blackbox et backup comme preuves d'intervention.
"@
Set-Content -Path (Join-Path $driveRoot "README_USB.txt") -Value $readme -Encoding UTF8

Write-Step "Validation"
$required = @(
    "$usbRoot\agent\windows\Invoke-RescueGrid.ps1",
    "$usbRoot\agent\windows\Start-RescueGrid.ps1",
    "$usbRoot\config\rescuegrid.env",
    (Join-Path $driveRoot "Start-RescueGrid.cmd")
)
foreach ($item in $required) {
    if (Test-Path $item) {
        Write-Host "OK $item" -ForegroundColor Green
    } else {
        Write-Host "MANQUANT $item" -ForegroundColor Red
    }
}

Write-Host ""
Write-Host "Clé RescueGrid préparée : $TargetDrive" -ForegroundColor Green
Write-Host "Lanceur : $TargetDrive\Start-RescueGrid.cmd" -ForegroundColor Green

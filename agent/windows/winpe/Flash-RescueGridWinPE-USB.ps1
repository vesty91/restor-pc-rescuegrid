<#
.SYNOPSIS
  Build boot.wim RescueGrid + rend la cle USB bootable (MakeWinPEMedia /UFD).

.DESCRIPTION
  1. Sauvegarde RescueGrid (hors winpe) hors de la cle
  2. Build-RescueGridWinPE.ps1 -Force
  3. MakeWinPEMedia /UFD (EFFACE la cle)
  4. Restore Create-RescueGridUSB + sauvegarde

  A lancer en administrateur.
#>
param(
    [string]$TargetDrive = "E:",
    [string]$WinPERoot = "C:\WinPE",
    [string]$DashboardUrl = "https://espace-client.restor-pc.fr",
    [string]$UploadApiKey = "",
    [switch]$SkipBuild
)

$ErrorActionPreference = "Stop"
$scriptDir = $PSScriptRoot
$projectAgent = $scriptDir

function Test-Admin {
    $p = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
    return $p.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}
if (-not (Test-Admin)) { throw "Lancer en administrateur." }

$driveLetter = $TargetDrive.TrimEnd(":").Trim()
$driveRoot = "${driveLetter}:"
if (-not (Test-Path "$driveRoot\")) { throw "Lecteur introuvable : $driveRoot" }

# Lire config existante si presente
$envFile = Join-Path $driveRoot "RescueGrid\config\rescuegrid.env"
if (Test-Path $envFile) {
    Get-Content $envFile -Encoding UTF8 | ForEach-Object {
        if ($_ -match '^\s*RESCUEGRID_DASHBOARD_URL=(.+)$') { $DashboardUrl = $Matches[1].Trim() }
        if ($_ -match '^\s*RESCUEGRID_UPLOAD_API_KEY=(.+)$') { $UploadApiKey = $Matches[1].Trim() }
    }
}

$backupRoot = Join-Path $env:TEMP ("RescueGridUSB_backup_" + (Get-Date -Format "yyyyMMdd_HHmmss"))
New-Item -ItemType Directory -Force -Path $backupRoot | Out-Null
Write-Host "Sauvegarde temporaire : $backupRoot" -ForegroundColor Cyan

$rg = Join-Path $driveRoot "RescueGrid"
if (Test-Path $rg) {
    # Copier tout sauf winpe (gros / sera recree)
    Get-ChildItem $rg -Force | Where-Object { $_.Name -ne "winpe" } | ForEach-Object {
        Copy-Item $_.FullName (Join-Path $backupRoot $_.Name) -Recurse -Force
    }
    Write-Host "RescueGrid sauvegarde (hors winpe)." -ForegroundColor Green
}

if (-not $SkipBuild) {
    Write-Host "`n=== Build boot.wim ===" -ForegroundColor Cyan
    & (Join-Path $scriptDir "Build-RescueGridWinPE.ps1") -WinPERoot $WinPERoot -Force
}

$adkRoot = @(
    "${env:ProgramFiles(x86)}\Windows Kits\10\Assessment and Deployment Kit",
    "$env:ProgramFiles\Windows Kits\10\Assessment and Deployment Kit"
) | Where-Object { Test-Path $_ } | Select-Object -First 1
$winpeDir = Join-Path $adkRoot "Windows Preinstallation Environment"
$deployTools = Join-Path $adkRoot "Deployment Tools"
$dandi = Join-Path $deployTools "DandISetEnv.bat"
$makeMedia = Join-Path $winpeDir "MakeWinPEMedia.cmd"

Write-Host "`n=== MakeWinPEMedia /UFD $WinPERoot -> $driveRoot (EFFACE LA CLE) ===" -ForegroundColor Yellow
$cmd = "call `"$dandi`" >nul && `"$makeMedia`" /UFD /F `"$WinPERoot`" $driveRoot"
cmd /c $cmd
if ($LASTEXITCODE -ne 0) { throw "MakeWinPEMedia a echoue (code $LASTEXITCODE)." }

Write-Host "`n=== Restore RescueGrid sur la cle ===" -ForegroundColor Cyan
$createParams = @{
    TargetDrive   = $driveRoot
    WinPEBasePath = $WinPERoot
    DashboardUrl  = $DashboardUrl
}
if ($UploadApiKey) { $createParams.UploadApiKey = $UploadApiKey }
& (Join-Path $scriptDir "Create-RescueGridUSB.ps1") @createParams

# Restaurer backup (agent/config/backup/reports...)
Get-ChildItem $backupRoot -Force -ErrorAction SilentlyContinue | ForEach-Object {
    $dest = Join-Path (Join-Path $driveRoot "RescueGrid") $_.Name
    if ($_.PSIsContainer) {
        New-Item -ItemType Directory -Force -Path $dest | Out-Null
        Copy-Item (Join-Path $_.FullName "*") $dest -Recurse -Force -ErrorAction SilentlyContinue
    } else {
        Copy-Item $_.FullName $dest -Force -ErrorAction SilentlyContinue
    }
}

# Verifs boot
$checks = @(
    (Join-Path $driveRoot "bootmgr"),
    (Join-Path $driveRoot "EFI"),
    (Join-Path $driveRoot "sources\boot.wim"),
    (Join-Path $driveRoot "RescueGrid\agent\windows\Start-RescueGrid.ps1"),
    (Join-Path $driveRoot "RescueGrid\winpe\boot.wim")
)
Write-Host "`n=== Controles ===" -ForegroundColor Cyan
foreach ($c in $checks) {
    if (Test-Path $c) { Write-Host "OK  $c" -ForegroundColor Green }
    else { Write-Host "MANQUANT  $c" -ForegroundColor Red }
}

Write-Host "`nCle bootable prete. Boot PC client : F12 / menu boot -> cle USB." -ForegroundColor Green
Write-Host "Sauvegarde temp conservee : $backupRoot" -ForegroundColor DarkGray

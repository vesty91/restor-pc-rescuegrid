<#
.SYNOPSIS
    [DÉPRÉCIÉ] Alias de compatibilité — utiliser Create-RescueGridUSB.ps1.

.DESCRIPTION
    Depuis v12.3, les deux anciens builders de clé USB (Create-RescueGridUSB.ps1
    et Build-RescueGridUSB.ps1) sont unifiés dans Create-RescueGridUSB.ps1, qui
    dispose désormais du formatage configurable (NTFS/FAT32) et de la copie
    boot.wim (ADK) précédemment propres à ce script.

    Ce fichier ne fait plus que traduire ses anciens paramètres et appeler
    Create-RescueGridUSB.ps1. Il est conservé uniquement pour ne pas casser les
    scripts/raccourcis existants qui l'invoquaient directement — préférez
    Create-RescueGridUSB.ps1 pour toute nouvelle utilisation.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File Build-RescueGridUSB.ps1 -UsbDriveLetter E -WinPEBasePath C:\WinPE
#>

param(
    [Parameter(Mandatory = $true)]
    [string]$UsbDriveLetter,

    [string]$WinPEBasePath = "C:\WinPE",

    [switch]$IncludeDataRecovery,

    [switch]$SkipFormat
)

Write-Host "[DEPRECIE] Build-RescueGridUSB.ps1 redirige vers Create-RescueGridUSB.ps1." -ForegroundColor Yellow
if ($IncludeDataRecovery) {
    Write-Host "[INFO] -IncludeDataRecovery n'a plus d'effet : les dossiers tools\testdisk et" -ForegroundColor Gray
    Write-Host "       tools\photorec sont toujours créés par Create-RescueGridUSB.ps1 (à remplir manuellement)." -ForegroundColor Gray
}

$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$targetScript = Join-Path $scriptRoot "Create-RescueGridUSB.ps1"

$driveLetter = $UsbDriveLetter.TrimEnd(":")
$targetDrive = "${driveLetter}:"

$forwardArgs = @{
    TargetDrive   = $targetDrive
    WinPEBasePath = $WinPEBasePath
}
if (-not $SkipFormat) {
    $forwardArgs["Format"] = $true
    $forwardArgs["FileSystem"] = "FAT32"
}

& $targetScript @forwardArgs

<#
.SYNOPSIS
  Installe ou supprime une tache planifiee Windows qui relance Invoke-RescueGrid.ps1
  en mode silencieux, pour une sauvegarde automatique periodique d'un poste client.

.DESCRIPTION
  Cree une tache planifiee (Register-ScheduledTask, executee en tant que SYSTEM)
  qui declenche une sauvegarde + upload ZIP vers le dashboard RescueGrid selon la
  frequence choisie, sans aucune interaction (-SilentMode -SkipConsent -CreateZip).

  IMPORTANT - Consentement client :
  Le consentement du client pour la collecte/sauvegarde automatique de ses donnees
  doit avoir ete obtenu manuellement AVANT l'installation de cette tache planifiee
  (voir docs/BACKUP_PLANIFIE.md). -SkipConsent supprime uniquement l'invite
  interactive lors des executions automatiques ulterieures -- il ne remplace jamais
  cet accord initial.

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File Register-RescueGridScheduledTask.ps1 `
      -ClientName "Dupont Jean" -BackupRoot "E:\RestorPC" -UserProfilePath "C:\Users\Dupont" `
      -DashboardUploadUrl "http://192.168.1.10:8000/upload" -UploadApiKey "xxx" `
      -Frequency Daily -TimeOfDay "03:30"

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File Register-RescueGridScheduledTask.ps1 -Unregister -ClientName "Dupont Jean"
#>

[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [string]$ClientName,

    [string]$BackupRoot,

    [string]$UserProfilePath,

    [switch]$BackupEssentialFoldersOnly,

    [string]$DashboardUploadUrl,

    [string]$UploadApiKey,

    [ValidateSet("Daily", "Weekly")]
    [string]$Frequency = "Daily",

    # Format HH:mm, 24h (ex: "03:30")
    [string]$TimeOfDay = "03:00",

    [string]$TaskName,

    [switch]$Unregister
)

$ErrorActionPreference = "Stop"

$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$agentScript = Join-Path $scriptRoot "Invoke-RescueGrid.ps1"

if (-not $TaskName) {
    if ($ClientName) {
        $safeName = ($ClientName -replace '[^a-zA-Z0-9_-]', '_')
        $TaskName = "RescueGrid_Backup_$safeName"
    } else {
        $TaskName = "RescueGrid_Backup"
    }
}

if ($Unregister) {
    if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
        Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
        Write-Host "Tache planifiee supprimee : $TaskName" -ForegroundColor Green
    } else {
        Write-Host "Aucune tache planifiee nommee '$TaskName'." -ForegroundColor Yellow
    }
    return
}

if (-not $ClientName) { throw "-ClientName est requis (sauf avec -Unregister)." }
if (-not $BackupRoot) { throw "-BackupRoot est requis (sauf avec -Unregister)." }
if (-not (Test-Path -LiteralPath $agentScript)) {
    throw "Invoke-RescueGrid.ps1 introuvable a cote de ce script : $agentScript"
}

$argParts = @(
    "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", "`"$agentScript`"",
    "-ClientName", "`"$ClientName`"",
    "-BackupRoot", "`"$BackupRoot`"",
    "-CreateZip", "-SilentMode", "-SkipConsent"
)
if ($UserProfilePath) { $argParts += "-UserProfilePath", "`"$UserProfilePath`"" }
if ($BackupEssentialFoldersOnly) { $argParts += "-BackupEssentialFoldersOnly" }
if ($DashboardUploadUrl) { $argParts += "-DashboardUploadUrl", "`"$DashboardUploadUrl`"" }
if ($UploadApiKey) { $argParts += "-UploadApiKey", "`"$UploadApiKey`"" }

try {
    $time = [DateTime]::ParseExact($TimeOfDay, "HH:mm", [System.Globalization.CultureInfo]::InvariantCulture)
} catch {
    throw "TimeOfDay invalide ('$TimeOfDay') - format attendu HH:mm, ex: 03:30"
}

$action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument ($argParts -join " ")

if ($Frequency -eq "Daily") {
    $trigger = New-ScheduledTaskTrigger -Daily -At $time
} else {
    $trigger = New-ScheduledTaskTrigger -Weekly -At $time -DaysOfWeek Sunday
}

# Execution en tant que SYSTEM : fonctionne sans session utilisateur ouverte et
# dispose des droits necessaires pour lire n'importe quel profil local.
$principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Hours 4) `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries

if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
    Write-Host "Tache existante '$TaskName' remplacee." -ForegroundColor Yellow
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
}

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Principal $principal -Settings $settings `
    -Description "Sauvegarde automatique RescueGrid pour $ClientName ($Frequency a $TimeOfDay)" | Out-Null

Write-Host ""
Write-Host "Tache planifiee installee : $TaskName" -ForegroundColor Green
Write-Host "  Frequence  : $Frequency a $TimeOfDay" -ForegroundColor Gray
Write-Host "  Sauvegarde : $BackupRoot" -ForegroundColor Gray
if ($DashboardUploadUrl) { Write-Host "  Upload     : $DashboardUploadUrl" -ForegroundColor Gray }
Write-Host ""
Write-Host "Rappel : le consentement client initial doit avoir ete obtenu manuellement" -ForegroundColor Yellow
Write-Host "avant d'activer une sauvegarde silencieuse recurrente. Voir docs/BACKUP_PLANIFIE.md." -ForegroundColor Yellow
Write-Host ""
Write-Host "Pour supprimer cette tache : Register-RescueGridScheduledTask.ps1 -Unregister -ClientName `"$ClientName`"" -ForegroundColor Gray

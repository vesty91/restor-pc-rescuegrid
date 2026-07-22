<#
.SYNOPSIS
    Lance l'agent RescueGrid avec de vrais parametres PowerShell (pas de concatenation CMD).
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $false)]
    [string]$ClientName,

    [string]$BackupRoot = "E:\RestorPC",
    [string]$UserProfilePath = "",
    [string]$OfflineWindowsPath = "",
    [switch]$BackupEssentialFoldersOnly,
    [switch]$SkipConsent,
    [switch]$CreateZip = $true,
    [switch]$Interactive
)

$ErrorActionPreference = "Stop"
try {
    [Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
    $OutputEncoding = [Console]::OutputEncoding
} catch {}

$rootDir = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$agent = Join-Path $rootDir "agent\windows\Invoke-RescueGrid.ps1"

if (-not (Test-Path $agent)) {
    Write-Host "[ERREUR] Agent introuvable : $agent" -ForegroundColor Red
    exit 1
}

if ($Interactive -or [string]::IsNullOrWhiteSpace($ClientName)) {
    Write-Host "============================================="
    Write-Host "   Restor-PC RescueGrid - Agent"
    Write-Host "============================================="
    Write-Host ""
    $ClientName = Read-Host "Nom du client"
    if ([string]::IsNullOrWhiteSpace($ClientName)) {
        Write-Host "[ERREUR] Nom du client obligatoire" -ForegroundColor Red
        exit 1
    }
    $rootIn = Read-Host "Dossier backup (defaut: E:\RestorPC)"
    if (-not [string]::IsNullOrWhiteSpace($rootIn)) { $BackupRoot = $rootIn }
    $UserProfilePath = Read-Host "Profil utilisateur (optionnel, Enter pour skip)"
    $OfflineWindowsPath = Read-Host "Chemin Windows offline (optionnel, Enter pour skip)"
    $ess = Read-Host "Mode essentiel (Bureau, Documents, etc.) ? (O/N)"
    $sk = Read-Host "Consentement automatique ? (O/N)"
    $BackupEssentialFoldersOnly = ($ess -eq "O" -or $ess -eq "o")
    $SkipConsent = ($sk -eq "O" -or $sk -eq "o")
    $CreateZip = $true
}

$argList = @(
    "-NoProfile",
    "-ExecutionPolicy", "Bypass",
    "-File", $agent,
    "-ClientName", $ClientName,
    "-BackupRoot", $BackupRoot
)
if ($UserProfilePath) { $argList += @("-UserProfilePath", $UserProfilePath) }
if ($OfflineWindowsPath) { $argList += @("-OfflineWindowsPath", $OfflineWindowsPath) }
if ($BackupEssentialFoldersOnly) { $argList += "-BackupEssentialFoldersOnly" }
if ($SkipConsent) { $argList += "-SkipConsent" }
if ($CreateZip) { $argList += "-CreateZip" }

Write-Host ""
Write-Host "Lancement agent (parametres PowerShell)..." -ForegroundColor Cyan
& powershell.exe @argList
exit $LASTEXITCODE

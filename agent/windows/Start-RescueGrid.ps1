<#
.SYNOPSIS
    Restor-PC RescueGrid - WinPE Atelier
.DESCRIPTION
    Menu interactif pour WinPE : diagnostic, sauvegarde, analyse SMART, réparation boot,
    export rapport, réinstallation. Conçu pour tourner depuis une clé USB WinPE.
.NOTES
    Auteur : Restor-PC RescueGrid
    Version : 1.0
    Lancement : powershell -ExecutionPolicy Bypass -File Start-RescueGrid.ps1
#>

param(
    [string]$BackupRoot = "X:\Interventions",
    [string]$RescueGridAgent = "$PSScriptRoot\Invoke-RescueGrid.ps1"
)

$ErrorActionPreference = "Continue"
$host.UI.RawUI.WindowTitle = "Restor-PC RescueGrid - WinPE Atelier"

# Fonctions utilitaires WinPE
function Get-WinPEDisks {
    Get-Disk | Select-Object Number, FriendlyName, BusType, HealthStatus, OperationalStatus, Size
}

function Get-WinPEVolumes {
    Get-Volume | Where-Object { $_.DriveLetter } | Select-Object DriveLetter, FileSystemLabel, FileSystem, SizeRemaining, Size
}

function Find-OfflineWindows {
    param([string]$DriveLetter)
    $winPath = "$DriveLetter`:\Windows"
    if (Test-Path "$winPath\System32") { return $winPath }
    return $null
}

function Find-AllWindowsInstallations {
    $windowsList = @()
    Get-Volume | Where-Object { $_.DriveLetter -and $_.DriveLetter -ne 'X' } | ForEach-Object {
        $wl = "$($_.DriveLetter):\Windows"
        if (Test-Path "$wl\System32") {
            $windowsList += [ordered]@{
                drive = "$($_.DriveLetter):"
                windows_path = $wl
                label = $_.FileSystemLabel
                size = "$([math]::Round($_.Size / 1GB, 2)) GB"
            }
        }
    }
    return $windowsList
}

function Show-Menu {
    param([string]$Title)
    Clear-Host
    Write-Host ""
    Write-Host "=============================================" -ForegroundColor Cyan
    Write-Host "   Restor-PC RescueGrid - WinPE Atelier" -ForegroundColor White
    Write-Host "=============================================" -ForegroundColor Cyan
    Write-Host "   $Title" -ForegroundColor Yellow
    Write-Host "=============================================" -ForegroundColor Cyan
    Write-Host ""
}

# Vérifier si l'agent est présent
if (-not (Test-Path -LiteralPath $RescueGridAgent)) {
    Write-Host "[AVERTISSEMENT] Invoke-RescueGrid.ps1 introuvable à : $RescueGridAgent" -ForegroundColor Yellow
    Write-Host "[INFO] Le diagnostic avance utilisera l'agent s'il est trouvé." -ForegroundColor Gray
}

# Menu principal
do {
    Show-Menu "Menu Principal"
    
    $offlineWindows = Find-AllWindowsInstallations
    $volumes = Get-WinPEVolumes
    
    Write-Host " Systeme actuel : WinPE" -ForegroundColor Cyan
    if ($offlineWindows.Count -gt 0) {
        Write-Host " Windows trouve(s) :" -ForegroundColor Green
        $i = 1
        foreach ($w in $offlineWindows) {
            Write-Host "   $i. $($w.windows_path) ($($w.label))" -ForegroundColor Gray
            $i++
        }
    }
    else {
        Write-Host " Aucun Windows detecte" -ForegroundColor Yellow
    }
    
    Write-Host ""
    Write-Host " Volumes disponibles :" -ForegroundColor Cyan
    foreach ($v in $volumes) {
        Write-Host "   $($v.DriveLetter): $($v.FileSystemLabel) - $([math]::Round($v.SizeRemaining / 1GB, 0))/ $([math]::Round($v.Size / 1GB, 0)) GB" -ForegroundColor Gray
    }
    
    Write-Host ""
    Write-Host " 1. Diagnostic complet" -ForegroundColor White
    Write-Host " 2. Sauvegarde utilisateur" -ForegroundColor White
    Write-Host " 3. Analyse SMART disques" -ForegroundColor White
    Write-Host " 4. Reparation boot Windows" -ForegroundColor White
    Write-Host " 5. Export rapport seul" -ForegroundColor White
    Write-Host " 6. Reinstallation (preparation)" -ForegroundColor White
    Write-Host " 7. Analyser Windows hors ligne" -ForegroundColor White
    Write-Host " 8. Verifier l'integrite systeme" -ForegroundColor White
    Write-Host " 9. Quitter" -ForegroundColor Red
    Write-Host ""
    $choice = Read-Host "Votre choix (1-9)"
    
    switch ($choice) {
        "1" { Invoke-Diagnostic }
        "2" { Invoke-Backup }
        "3" { Invoke-SMART }
        "4" { Invoke-BootRepair }
        "5" { Invoke-Report }
        "6" { Invoke-Reinstall }
        "7" { Invoke-Offline }
        "8" { Invoke-SystemCheck }
        "9" { Write-Host "Au revoir." -ForegroundColor Cyan; break }
    }
} while ($choice -ne "9")

# ===== FONCTIONS =====

function Invoke-Diagnostic {
    Show-Menu "Diagnostic complet"
    
    $clientName = Read-Host "Nom du client"
    
    # Chercher Windows offline
    $offlinePath = ""
    $windowsList = Find-AllWindowsInstallations
    if ($windowsList.Count -eq 1) {
        $offlinePath = $windowsList[0].windows_path
        Write-Host "[INFO] Windows detecte : $offlinePath" -ForegroundColor Green
    }
    elseif ($windowsList.Count -gt 1) {
        Write-Host "Windows disponibles :"
        for ($i = 0; $i -lt $windowsList.Count; $i++) {
            Write-Host "  $($i+1). $($windowsList[$i].windows_path)"
        }
        $idx = Read-Host "Choisir (1-$($windowsList.Count))"
        $offlinePath = $windowsList[[int]$idx - 1].windows_path
    }
    
    if (Test-Path -LiteralPath $RescueGridAgent) {
        $params = @(
            "-ClientName", $clientName,
            "-BackupRoot", $BackupRoot,
            "-CreateZip"
        )
        if ($offlinePath) {
            $params += "-OfflineWindowsPath", $offlinePath
        }
        powershell -ExecutionPolicy Bypass -File $RescueGridAgent @params
    }
    else {
        Write-Host "[MODE DEGRADE] Diagnostic sans agent..." -ForegroundColor Yellow
        $disks = Get-WinPEDisks
        $diskText = $disks | Format-Table | Out-String
        $diskText | Out-File -FilePath "$BackupRoot\winpe_diagnostic.txt" -Encoding utf8
        Write-Host "Diagnostic de base ecrit dans $BackupRoot\winpe_diagnostic.txt" -ForegroundColor Green
    }
    
    Pause
}

function Invoke-Backup {
    Show-Menu "Sauvegarde utilisateur"
    
    $clientName = Read-Host "Nom du client"
    
    # Chercher les profils utilisateurs
    $windowsList = Find-AllWindowsInstallations
    $profilesFound = @()
    
    foreach ($w in $windowsList) {
        $usersPath = "$(Split-Path $w.windows_path -Parent)\Users"
        if (Test-Path $usersPath) {
            Get-ChildItem $usersPath -Directory -ErrorAction SilentlyContinue |
                Where-Object { $_.Name -notin @("All Users", "Default", "Default User", "Public") } |
                ForEach-Object {
                    $profilesFound += "$(Split-Path $w.windows_path -Parent):\$($_.Name)"
                }
        }
    }
    
    if ($profilesFound.Count -gt 0) {
        Write-Host "Profils trouves :" -ForegroundColor Green
        for ($i = 0; $i -lt $profilesFound.Count; $i++) {
            Write-Host "  $($i+1). $($profilesFound[$i])"
        }
        $pIdx = Read-Host "Choisir un profil (1-$($profilesFound.Count)) ou Enter pour saisir manuellement"
        if ($pIdx) {
            $profilePath = $profilesFound[[int]$pIdx - 1]
        }
        else {
            $profilePath = Read-Host "Chemin du profil (ex: C:\Users\Client)"
        }
    }
    else {
        $profilePath = Read-Host "Chemin du profil (ex: C:\Users\Client)"
    }
    
    Write-Host "Mode essentiel (Bureau, Documents, etc.) ? (O/N)" -NoNewline
    $essential = Read-Host
    
    if (Test-Path -LiteralPath $RescueGridAgent) {
        $params = @(
            "-ClientName", $clientName,
            "-BackupRoot", $BackupRoot,
            "-UserProfilePath", $profilePath,
            "-CreateZip"
        )
        if ($essential -eq "O" -or $essential -eq "o") {
            $params += "-BackupEssentialFoldersOnly"
        }
        powershell -ExecutionPolicy Bypass -File $RescueGridAgent @params
    }
    else {
        Write-Host "[ERREUR] Agent introuvable pour la sauvegarde." -ForegroundColor Red
    }
    
    Pause
}

function Invoke-SMART {
    Show-Menu "Analyse SMART disques"
    
    $disks = Get-WinPEDisks
    Write-Host "Disques detectes :" -ForegroundColor Cyan
    $disks | Format-Table Number, FriendlyName, HealthStatus, OperationalStatus, @{N="Size(GB)";E={[math]::Round($_.Size/1GB,2)}} | Out-String | ForEach-Object { Write-Host $_ }
    
    $smartctl = Get-Command smartctl -ErrorAction SilentlyContinue
    if ($smartctl) {
        Write-Host "smartctl disponible. Analyse approfondie..." -ForegroundColor Green
        foreach ($disk in $disks) {
            Write-Host "  Disque $($disk.Number)..." -NoNewline
            & $smartctl.Source -a "/dev/sd$($disk.Number)" 2>&1 | Select-String "Reallocated|Pending|Temperature|Health|SMART" -ErrorAction SilentlyContinue | ForEach-Object { Write-Host "    $_" -ForegroundColor Gray }
            Write-Host " OK" -ForegroundColor Green
        }
    }
    else {
        Write-Host "smartctl non disponible sous WinPE." -ForegroundColor Yellow
        Write-Host "Installation : copier smartctl.exe sur la cle USB." -ForegroundColor Gray
    }
    
    Pause
}

function Invoke-BootRepair {
    Show-Menu "Reparation boot Windows"
    
    Write-Host "=== OUTILS DE REPARATION BOOT ===" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "1. Reconstruire BCD (bootrec /rebuildbcd)" -ForegroundColor White
    Write-Host "2. Reparer MBR (bootrec /fixmbr)" -ForegroundColor White
    Write-Host "3. Reparer secteur boot (bootrec /fixboot)" -ForegroundColor White
    Write-Host "4. Tout reparer (1+2+3)" -ForegroundColor White
    Write-Host "5. Retour" -ForegroundColor Red
    Write-Host ""
    
    $choice = Read-Host "Votre choix (1-5)"
    
    switch ($choice) {
        "1" {
            Write-Host "Execution : bootrec /rebuildbcd..." -ForegroundColor Yellow
            bootrec /rebuildbcd 2>&1 | Out-Host
            Pause
        }
        "2" {
            Write-Host "Execution : bootrec /fixmbr..." -ForegroundColor Yellow
            bootrec /fixmbr 2>&1 | Out-Host
            Pause
        }
        "3" {
            Write-Host "Execution : bootrec /fixboot..." -ForegroundColor Yellow
            bootrec /fixboot 2>&1 | Out-Host
            Pause
        }
        "4" {
            Write-Host "Execution : bootrec /fixmbr..." -ForegroundColor Yellow
            bootrec /fixmbr 2>&1 | Out-Host
            Write-Host "Execution : bootrec /fixboot..." -ForegroundColor Yellow
            bootrec /fixboot 2>&1 | Out-Host
            Write-Host "Execution : bootrec /rebuildbcd..." -ForegroundColor Yellow
            bootrec /rebuildbcd 2>&1 | Out-Host
            Pause
        }
    }
}

function Invoke-Report {
    Show-Menu "Export rapport seul"
    
    $clientName = Read-Host "Nom du client"
    
    if (Test-Path -LiteralPath $RescueGridAgent) {
        powershell -ExecutionPolicy Bypass -File $RescueGridAgent -ClientName $clientName -BackupRoot $BackupRoot
    }
    else {
        Write-Host "[ERREUR] Agent introuvable." -ForegroundColor Red
    }
    
    Pause
}

function Invoke-Reinstall {
    Show-Menu "Preparation reinstallation"
    
    Write-Host "=== AVANT REINSTALLATION ===" -ForegroundColor Red
    Write-Host ""
    Write-Host "IMPORTANT :" -ForegroundColor Yellow
    Write-Host "1. Effectuer d'abord un diagnostic complet (option 1)" -ForegroundColor White
    Write-Host "2. Sauvegarder le profil utilisateur (option 2)" -ForegroundColor White
    Write-Host "3. Verifier que le backup est complet" -ForegroundColor White
    Write-Host "4. Verifier le risque disque" -ForegroundColor White
    Write-Host ""
    Write-Host "Reinstallation Windows :" -ForegroundColor Cyan
    Write-Host "  - Monter l'ISO Windows avec :" -ForegroundColor Gray
    Write-Host "    dism /Mount-Image /ImageFile:X:\sources\install.wim /index:1 /MountDir:C:\mount" -ForegroundColor Gray
    Write-Host "  - Lancer setup.exe depuis le lecteur DVD/ISO monte" -ForegroundColor Gray
    Write-Host ""
    
    Pause
}

function Invoke-Offline {
    Show-Menu "Analyse Windows hors ligne"
    
    $clientName = Read-Host "Nom du client"
    $windowsList = Find-AllWindowsInstallations
    
    if ($windowsList.Count -eq 0) {
        Write-Host "[ERREUR] Aucune installation Windows trouvee." -ForegroundColor Red
        Pause
        return
    }
    
    Write-Host "Windows disponibles :"
    for ($i = 0; $i -lt $windowsList.Count; $i++) {
        Write-Host "  $($i+1). $($windowsList[$i].windows_path)"
    }
    $idx = Read-Host "Choisir (1-$($windowsList.Count))"
    $offlinePath = $windowsList[[int]$idx - 1].windows_path
    
    if (Test-Path -LiteralPath $RescueGridAgent) {
        powershell -ExecutionPolicy Bypass -File $RescueGridAgent -ClientName $clientName -BackupRoot $BackupRoot -OfflineWindowsPath $offlinePath -CreateZip
    }
    else {
        Write-Host "[MODE DEGRADE] Copie manuelle des artefacts..." -ForegroundColor Yellow
        $outputDir = "$BackupRoot\Offline_$clientName"
        New-Item -ItemType Directory -Path $outputDir -Force | Out-Null
        
        # Copie ruches
        $configPath = "$offlinePath\System32\Config"
        foreach ($hive in @("SYSTEM", "SOFTWARE", "SAM", "SECURITY", "DEFAULT")) {
            if (Test-Path "$configPath\$hive") {
                Copy-Item "$configPath\$hive" "$outputDir\" -Force -ErrorAction SilentlyContinue
            }
        }
        
        # Copie journaux
        $logsPath = "$offlinePath\System32\winevt\Logs"
        if (Test-Path $logsPath) {
            Copy-Item "$logsPath\*.evtx" "$outputDir\eventlogs\" -Force -ErrorAction SilentlyContinue
        }
        
        Write-Host "Artefacts copies dans $outputDir" -ForegroundColor Green
    }
    
    Pause
}

function Invoke-SystemCheck {
    Show-Menu "Verification integrite systeme"
    
    Write-Host "=== VERIFICATION SYSTEME ===" -ForegroundColor Cyan
    
    # Disques
    Write-Host "[1/4] Verification disques..." -NoNewline
    $disks = Get-WinPEDisks
    $issues = @($disks | Where-Object { $_.HealthStatus -ne "Healthy" })
    if ($issues.Count -gt 0) {
        Write-Host " PROBLEMES DETECTES" -ForegroundColor Red
        $issues | Format-Table Number, FriendlyName, HealthStatus
    }
    else {
        Write-Host " OK" -ForegroundColor Green
    }
    
    # Volumes
    Write-Host "[2/4] Verification volumes..." -NoNewline
    $vols = Get-WinPEVolumes
    $lowSpace = @($vols | Where-Object { $_.SizeRemaining -and $_.Size -and ($_.SizeRemaining / $_.Size) -lt 0.1 })
    if ($lowSpace.Count -gt 0) {
        Write-Host " ESPACE FAIBLE" -ForegroundColor Yellow
        $lowSpace | Format-Table DriveLetter, @{N="Libre%";E={[math]::Round($_.SizeRemaining/$_.Size*100,0)}}
    }
    else {
        Write-Host " OK" -ForegroundColor Green
    }
    
    # RAM
    Write-Host "[3/4] Verification RAM..." -NoNewline
    $ram = Get-CimInstance Win32_ComputerSystem -ErrorAction SilentlyContinue
    if ($ram.TotalPhysicalMemory -lt 4GB) {
        Write-Host " $([math]::Round($ram.TotalPhysicalMemory/1GB,2)) GB (FAIBLE)" -ForegroundColor Yellow
    }
    else {
        Write-Host " $([math]::Round($ram.TotalPhysicalMemory/1GB,2)) GB" -ForegroundColor Green
    }
    
    # BitLocker
    Write-Host "[4/4] Verification BitLocker..." -NoNewline
    $bde = manage-bde -status 2>&1
    if ($bde -match "Locked") {
        Write-Host " VOLUMES VERROUILLES" -ForegroundColor Yellow
    }
    else {
        Write-Host " OK" -ForegroundColor Green
    }
    
    Write-Host ""
    Write-Host "Resume :" -ForegroundColor Cyan
    Write-Host "  Disques : $(@($disks).Count) dont $(@($issues).Count) problemes" -ForegroundColor Gray
    Write-Host "  Volumes : $(@($vols).Count) dont $(@($lowSpace).Count) espace faible" -ForegroundColor Gray
    Write-Host "  RAM     : $([math]::Round($ram.TotalPhysicalMemory/1GB,2)) GB" -ForegroundColor Gray
    
    Pause
}
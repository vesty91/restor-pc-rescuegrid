<#
.SYNOPSIS
    Restor-PC RescueGrid - WinPE Atelier
.DESCRIPTION
    Menu interactif pour WinPE : diagnostic, sauvegarde, analyse SMART, reparation boot,
    export rapport, reinstallation. Concu pour tourner depuis une cle USB WinPE.
    Sous Windows live : interface graphique (-Gui, defaut via Start-RescueGrid.cmd).
.NOTES
    Auteur : Restor-PC RescueGrid
    Version : 1.1
    Lancement : powershell -STA -ExecutionPolicy Bypass -File Start-RescueGrid.ps1 -Gui
#>

param(
    [string]$BackupRoot = "X:\Interventions",
    [string]$RescueGridAgent = "$PSScriptRoot\Invoke-RescueGrid.ps1",
    [string]$DashboardUploadUrl,
    [string]$UploadApiKey,
    [string]$RescueGridEnvPath,
    # Interface graphique (WinForms). Recommande sous Windows live.
    [switch]$Gui,
    # Force le menu texte (WinPE / depannage).
    [switch]$Console
)

$ErrorActionPreference = "Continue"
$host.UI.RawUI.WindowTitle = "Restor-PC RescueGrid - WinPE Atelier"
$script:RescueGridGuiMode = $false

function Import-RescueGridEnv {
    <# Voir Invoke-RescueGrid.ps1 pour le detail : charge rescuegrid.env (cle USB
       ou dossier du script) et retourne un hashtable des variables RESCUEGRID_*. #>
    param([string]$ExplicitPath)

    $result = @{}
    $candidates = @()
    if ($ExplicitPath) { $candidates += $ExplicitPath }
    if ($env:RESCUEGRID_ENV_PATH) { $candidates += $env:RESCUEGRID_ENV_PATH }
    if ($PSScriptRoot) {
        $candidates += Join-Path $PSScriptRoot "..\..\config\rescuegrid.env"
        $candidates += Join-Path $PSScriptRoot "rescuegrid.env"
    }
    foreach ($path in $candidates) {
        if ($path -and (Test-Path $path -PathType Leaf)) {
            try {
                Get-Content -Path $path -Encoding UTF8 -ErrorAction Stop | ForEach-Object {
                    $line = $_.Trim()
                    if ($line -and -not $line.StartsWith("#") -and $line.Contains("=")) {
                        $parts = $line.Split("=", 2)
                        $result[$parts[0].Trim()] = $parts[1].Trim()
                    }
                }
                Write-Host "[CONFIG] rescuegrid.env charge : $path" -ForegroundColor DarkGray
                return $result
            } catch {
                Write-Host "[CONFIG] Lecture impossible de $path : $_" -ForegroundColor Yellow
            }
        }
    }
    return $result
}

$RescueGridConfig = Import-RescueGridEnv -ExplicitPath $RescueGridEnvPath
if (-not $PSBoundParameters.ContainsKey('BackupRoot') -and $RescueGridConfig.ContainsKey('RESCUEGRID_BACKUP_ROOT')) {
    $BackupRoot = $RescueGridConfig['RESCUEGRID_BACKUP_ROOT']
}
if (-not $DashboardUploadUrl -and $RescueGridConfig.ContainsKey('RESCUEGRID_DASHBOARD_URL')) {
    $DashboardUploadUrl = "{0}/upload" -f $RescueGridConfig['RESCUEGRID_DASHBOARD_URL'].TrimEnd('/')
}
if (-not $UploadApiKey -and $RescueGridConfig.ContainsKey('RESCUEGRID_UPLOAD_API_KEY')) {
    $UploadApiKey = $RescueGridConfig['RESCUEGRID_UPLOAD_API_KEY']
}
if ($DashboardUploadUrl) {
    Write-Host "[CONFIG] Upload automatique vers $DashboardUploadUrl" -ForegroundColor DarkGray
}

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

function Test-IsWinPE {
    return ($env:SystemDrive -eq 'X:') -or (Test-Path 'HKLM:\SYSTEM\CurrentControlSet\Control\MiniNT')
}

function Find-AllWindowsInstallations {
    # PSCustomObject (pas [ordered]) pour eviter que PowerShell enumere les cles
    # au return et affiche 4 lignes vides pour 1 Windows.
    $windowsList = [System.Collections.Generic.List[object]]::new()
    Get-Volume | Where-Object { $_.DriveLetter -and $_.DriveLetter -ne 'X' } | ForEach-Object {
        $wl = "$($_.DriveLetter):\Windows"
        if (Test-Path "$wl\System32") {
            $windowsList.Add([pscustomobject]@{
                drive        = "$($_.DriveLetter):"
                windows_path = $wl
                label        = $_.FileSystemLabel
                size         = "$([math]::Round($_.Size / 1GB, 2)) GB"
            }) | Out-Null
        }
    }
    return , @($windowsList.ToArray())
}

$GuiHelpersPath = Join-Path $PSScriptRoot "RescueGrid.GuiHelpers.ps1"
if (Test-Path -LiteralPath $GuiHelpersPath) {
    . $GuiHelpersPath
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

# Verifier si l'agent est present
if (-not (Test-Path -LiteralPath $RescueGridAgent)) {
    Write-Host "[AVERTISSEMENT] Invoke-RescueGrid.ps1 introuvable a : $RescueGridAgent" -ForegroundColor Yellow
    Write-Host "[INFO] Le diagnostic avance utilisera l'agent s'il est trouve." -ForegroundColor Gray
}

# ===== FONCTIONS =====

function Read-ClientFicheInfoGui {
    Add-Type -AssemblyName System.Windows.Forms
    Add-Type -AssemblyName System.Drawing
    $form = New-Object System.Windows.Forms.Form
    $form.Text = "Fiche client - Restor-PC"
    $form.Size = New-Object System.Drawing.Size(520, 620)
    $form.StartPosition = "CenterScreen"
    $form.FormBorderStyle = "FixedDialog"
    $form.MaximizeBox = $false
    $form.BackColor = [System.Drawing.Color]::FromArgb(8, 20, 38)
    $form.ForeColor = [System.Drawing.Color]::White
    $form.Font = New-Object System.Drawing.Font("Segoe UI", 10)
    $form.Padding = New-Object System.Windows.Forms.Padding(24)

    $y = 16
    $logoPath = Join-Path $PSScriptRoot "assets\restorpc_logo.png"
    if (Test-Path -LiteralPath $logoPath) {
        $pic = New-Object System.Windows.Forms.PictureBox
        $pic.SizeMode = [System.Windows.Forms.PictureBoxSizeMode]::Zoom
        $pic.Location = New-Object System.Drawing.Point(28, $y)
        $pic.Size = New-Object System.Drawing.Size(160, 56)
        $pic.Image = [System.Drawing.Image]::FromFile($logoPath)
        $form.Controls.Add($pic)
        $hdr = New-Object System.Windows.Forms.Label
        $hdr.Text = "Fiche client"
        $hdr.Font = New-Object System.Drawing.Font("Segoe UI", 14, [System.Drawing.FontStyle]::Bold)
        $hdr.ForeColor = [System.Drawing.Color]::FromArgb(0, 163, 255)
        $hdr.Location = New-Object System.Drawing.Point(210, 28)
        $hdr.Size = New-Object System.Drawing.Size(260, 32)
        $form.Controls.Add($hdr)
        $y = 88
    } else {
        $hdr = New-Object System.Windows.Forms.Label
        $hdr.Text = "Fiche client"
        $hdr.Font = New-Object System.Drawing.Font("Segoe UI", 14, [System.Drawing.FontStyle]::Bold)
        $hdr.ForeColor = [System.Drawing.Color]::FromArgb(0, 163, 255)
        $hdr.Location = New-Object System.Drawing.Point(28, $y)
        $hdr.Size = New-Object System.Drawing.Size(440, 28)
        $form.Controls.Add($hdr)
        $y = 56
    }

    $hint = New-Object System.Windows.Forms.Label
    $hint.Text = "Renseigne les infos client pour le dashboard et les emails."
    $hint.ForeColor = [System.Drawing.Color]::FromArgb(147, 169, 197)
    $hint.Location = New-Object System.Drawing.Point(28, $y)
    $hint.Size = New-Object System.Drawing.Size(450, 22)
    $form.Controls.Add($hint)
    $y = $y + 36

    $fieldDefs = @(
        @{ Key = "Name"; Label = "Nom du client *" },
        @{ Key = "Email"; Label = "Email (recommande)" },
        @{ Key = "Phone"; Label = "Telephone" },
        @{ Key = "Address"; Label = "Adresse" },
        @{ Key = "Contact"; Label = "Contact (interlocuteur)" }
    )
    $boxes = @{}
    foreach ($f in $fieldDefs) {
        $lbl = New-Object System.Windows.Forms.Label
        $lbl.Text = $f.Label
        $lbl.Location = New-Object System.Drawing.Point(28, $y)
        $lbl.Size = New-Object System.Drawing.Size(450, 22)
        $form.Controls.Add($lbl)
        $y = $y + 26

        $tb = New-Object System.Windows.Forms.TextBox
        $tb.Location = New-Object System.Drawing.Point(28, $y)
        $tb.Size = New-Object System.Drawing.Size(450, 32)
        $tb.Font = New-Object System.Drawing.Font("Segoe UI", 11)
        $tb.BackColor = [System.Drawing.Color]::FromArgb(13, 30, 52)
        $tb.ForeColor = [System.Drawing.Color]::White
        $tb.BorderStyle = "FixedSingle"
        $form.Controls.Add($tb)
        $boxes[$f.Key] = $tb
        $y = $y + 48
    }

    $chkMail = New-Object System.Windows.Forms.CheckBox
    $chkMail.Text = "Envoyer le rapport par mail a la fin"
    $chkMail.Location = New-Object System.Drawing.Point(28, $y)
    $chkMail.Size = New-Object System.Drawing.Size(450, 28)
    $chkMail.ForeColor = [System.Drawing.Color]::FromArgb(0, 180, 255)
    $form.Controls.Add($chkMail)
    $y = $y + 44

    $ok = New-Object System.Windows.Forms.Button
    $ok.Text = "Continuer"
    $ok.Location = New-Object System.Drawing.Point(248, $y)
    $ok.Size = New-Object System.Drawing.Size(120, 38)
    $ok.BackColor = [System.Drawing.Color]::FromArgb(10, 132, 255)
    $ok.ForeColor = [System.Drawing.Color]::White
    $ok.FlatStyle = "Flat"
    $ok.DialogResult = [System.Windows.Forms.DialogResult]::OK
    $form.Controls.Add($ok)
    $form.AcceptButton = $ok

    $cancel = New-Object System.Windows.Forms.Button
    $cancel.Text = "Annuler"
    $cancel.Location = New-Object System.Drawing.Point(378, $y)
    $cancel.Size = New-Object System.Drawing.Size(100, 38)
    $cancel.DialogResult = [System.Windows.Forms.DialogResult]::Cancel
    $form.Controls.Add($cancel)
    $form.CancelButton = $cancel

    $needed = $y + 90
    if ($form.ClientSize.Height -lt $needed) {
        $form.ClientSize = New-Object System.Drawing.Size(504, $needed)
    }

    $result = $form.ShowDialog()
    if ($pic -and $pic.Image) { $pic.Image.Dispose() }
    if ($result -ne [System.Windows.Forms.DialogResult]::OK) { return $null }
    if ([string]::IsNullOrWhiteSpace($boxes.Name.Text)) {
        [System.Windows.Forms.MessageBox]::Show("Le nom du client est obligatoire.", "Restor-PC") | Out-Null
        return Read-ClientFicheInfoGui
    }
    if ([string]::IsNullOrWhiteSpace($boxes.Email.Text)) {
        $r = [System.Windows.Forms.MessageBox]::Show(
            "Sans email : pas denvoi auto (rapport, RDV, devis). Continuer ?",
            "Email recommande",
            [System.Windows.Forms.MessageBoxButtons]::YesNo,
            [System.Windows.Forms.MessageBoxIcon]::Warning
        )
        if ($r -ne [System.Windows.Forms.DialogResult]::Yes) { return Read-ClientFicheInfoGui }
    }
    return [pscustomobject]@{
        Name       = $boxes.Name.Text.Trim()
        Email      = $boxes.Email.Text.Trim()
        Phone      = $boxes.Phone.Text.Trim()
        Address    = $boxes.Address.Text.Trim()
        Contact    = $boxes.Contact.Text.Trim()
        SendReport = [bool]$chkMail.Checked
    }
}

function Read-ClientFicheInfo {
    <#
      Saisie fiche client apres le nom : email / tel / adresse / contact.
      Mode GUI si RescueGridGuiMode, sinon invite console.
    #>
    if ($script:RescueGridGuiMode) {
        return Read-ClientFicheInfoGui
    }
    Write-Host ""
    Write-Host "--- Fiche client (Entree = passer) ---" -ForegroundColor Cyan
    $name = Read-Host "Nom du client"
    while ([string]::IsNullOrWhiteSpace($name)) {
        Write-Host "Le nom est obligatoire." -ForegroundColor Yellow
        $name = Read-Host "Nom du client"
    }
    $email = (Read-Host "Email (recommande - devis, factures, RDV)").Trim()
    if (-not $email) {
        Write-Host "[ATTENTION] Sans email : pas denvoi auto (rapport, RDV, devis)." -ForegroundColor Yellow
        $cont = Read-Host "Continuer sans email ? (O/N)"
        if ($cont -ne "O" -and $cont -ne "o") {
            $email = (Read-Host "Email").Trim()
        }
    }
    $phone = (Read-Host "Telephone").Trim()
    $address = (Read-Host "Adresse").Trim()
    $contact = (Read-Host "Contact (prenom/nom interlocuteur)").Trim()
    $sendReport = $false
    if ($email) {
        $sendAns = Read-Host "Envoyer le rapport par mail a la fin ? (O/N)"
        $sendReport = ($sendAns -eq "O" -or $sendAns -eq "o")
    }
    return [pscustomobject]@{
        Name       = $name.Trim()
        Email      = $email
        Phone      = $phone
        Address    = $address
        Contact    = $contact
        SendReport = $sendReport
    }
}

function Add-ClientFicheParams {
    param(
        [Parameter(Mandatory)][object]$Fiche,
        [Parameter(Mandatory)][System.Collections.IList]$Params
    )
    $Params.Add("-ClientName") | Out-Null
    $Params.Add($Fiche.Name) | Out-Null
    if ($Fiche.Email) { $Params.Add("-ClientEmail") | Out-Null; $Params.Add($Fiche.Email) | Out-Null }
    if ($Fiche.Phone) { $Params.Add("-ClientPhone") | Out-Null; $Params.Add($Fiche.Phone) | Out-Null }
    if ($Fiche.Address) { $Params.Add("-ClientAddress") | Out-Null; $Params.Add($Fiche.Address) | Out-Null }
    if ($Fiche.Contact) { $Params.Add("-ClientContact") | Out-Null; $Params.Add($Fiche.Contact) | Out-Null }
    if ($Fiche.SendReport) { $Params.Add("-SendReportEmail") | Out-Null }
}

function Invoke-Diagnostic {
    Show-Menu "Diagnostic complet"
    
    $fiche = Read-ClientFicheInfo
    if (-not $fiche) { return }
    
    # Chercher Windows offline
    $offlinePath = ""
    $windowsList = @(Find-AllWindowsInstallations)
    if ($windowsList.Count -eq 1) {
        $offlinePath = $windowsList[0].windows_path
        Write-Host "[INFO] Windows detecte : $offlinePath" -ForegroundColor Green
    }
    elseif ($windowsList.Count -gt 1) {
        if ($script:RescueGridGuiMode -and (Get-Command Select-WindowsInstallGui -ErrorAction SilentlyContinue)) {
            $offlinePath = Select-WindowsInstallGui -WindowsList $windowsList
            if (-not $offlinePath) { return }
        } else {
            Write-Host "Windows disponibles :"
            for ($i = 0; $i -lt $windowsList.Count; $i++) {
                Write-Host "  $($i+1). $($windowsList[$i].windows_path)"
            }
            $idx = Read-Host "Choisir (1-$($windowsList.Count))"
            $offlinePath = $windowsList[[int]$idx - 1].windows_path
        }
    }
    
    if (Test-Path -LiteralPath $RescueGridAgent) {
        $params = [System.Collections.ArrayList]@(
            "-BackupRoot", $BackupRoot,
            "-CreateZip"
        )
        Add-ClientFicheParams -Fiche $fiche -Params $params
        # Hors WinPE : ne pas forcer OfflineWindowsPath sur le Windows en cours
        # (sinon inventaire "offline" au lieu du diagnostic live).
        $liveWindows = Join-Path $env:SystemDrive "Windows"
        if ($offlinePath -and ((Test-IsWinPE) -or ($offlinePath -ne $liveWindows))) {
            $params.Add("-OfflineWindowsPath") | Out-Null
            $params.Add($offlinePath) | Out-Null
        }
        if ($DashboardUploadUrl) { $params.Add("-DashboardUploadUrl") | Out-Null; $params.Add($DashboardUploadUrl) | Out-Null }
        if ($UploadApiKey) { $params.Add("-UploadApiKey") | Out-Null; $params.Add($UploadApiKey) | Out-Null }

        if ($script:RescueGridGuiMode -and (Get-Command Invoke-AgentWithProgress -ErrorAction SilentlyContinue)) {
            [void](Invoke-AgentWithProgress -AgentPath $RescueGridAgent -AgentParams $params -Title "Diagnostic en cours...")
        } else {
            powershell -ExecutionPolicy Bypass -File $RescueGridAgent @params
        }

        # Signature client en fin d'intervention (GUI)
        if ($script:RescueGridGuiMode -and (Get-Command Show-ClientSignaturePad -ErrorAction SilentlyContinue)) {
            $latest = Get-LatestInterventionFolder -BackupRoot $BackupRoot
            if ($latest) {
                $sigPath = Join-Path $latest.FullName "signature_client.png"
                $saved = Show-ClientSignaturePad -OutPath $sigPath
                if ($saved) {
                    $zipPath = "$($latest.FullName).zip"
                    if (Test-Path $zipPath) {
                        [void](Add-FileToZip -ZipPath $zipPath -FilePath $saved -EntryName "signature_client.png")
                    }
                    Write-Host "[OK] Signature enregistree : $saved" -ForegroundColor Green
                }
            }
        }
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
    
    $fiche = Read-ClientFicheInfo
    if (-not $fiche) { return }
    
    # Chercher les profils utilisateurs
    $windowsList = @(Find-AllWindowsInstallations)
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
        $params = [System.Collections.ArrayList]@(
            "-BackupRoot", $BackupRoot,
            "-UserProfilePath", $profilePath,
            "-CreateZip"
        )
        Add-ClientFicheParams -Fiche $fiche -Params $params
        if ($essential -eq "O" -or $essential -eq "o") {
            $params.Add("-BackupEssentialFoldersOnly") | Out-Null
        }
        if ($DashboardUploadUrl) { $params.Add("-DashboardUploadUrl") | Out-Null; $params.Add($DashboardUploadUrl) | Out-Null }
        if ($UploadApiKey) { $params.Add("-UploadApiKey") | Out-Null; $params.Add($UploadApiKey) | Out-Null }
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
    
    $fiche = Read-ClientFicheInfo
    if (-not $fiche) { return }
    
    if (Test-Path -LiteralPath $RescueGridAgent) {
        $params = [System.Collections.ArrayList]@("-BackupRoot", $BackupRoot, "-CreateZip")
        Add-ClientFicheParams -Fiche $fiche -Params $params
        if ($DashboardUploadUrl) { $params.Add("-DashboardUploadUrl") | Out-Null; $params.Add($DashboardUploadUrl) | Out-Null }
        if ($UploadApiKey) { $params.Add("-UploadApiKey") | Out-Null; $params.Add($UploadApiKey) | Out-Null }
        powershell -ExecutionPolicy Bypass -File $RescueGridAgent @params
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
    
    $fiche = Read-ClientFicheInfo
    if (-not $fiche) { return }
    $windowsList = @(Find-AllWindowsInstallations)
    
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
        $params = [System.Collections.ArrayList]@(
            "-BackupRoot", $BackupRoot,
            "-OfflineWindowsPath", $offlinePath,
            "-CreateZip"
        )
        Add-ClientFicheParams -Fiche $fiche -Params $params
        if ($DashboardUploadUrl) { $params.Add("-DashboardUploadUrl") | Out-Null; $params.Add($DashboardUploadUrl) | Out-Null }
        if ($UploadApiKey) { $params.Add("-UploadApiKey") | Out-Null; $params.Add($UploadApiKey) | Out-Null }
        powershell -ExecutionPolicy Bypass -File $RescueGridAgent @params
    }
    else {
        Write-Host "[MODE DEGRADE] Copie manuelle des artefacts..." -ForegroundColor Yellow
        $outputDir = "$BackupRoot\Offline_$($fiche.Name)"
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

function Show-RescueGridGui {
    Add-Type -AssemblyName System.Windows.Forms
    Add-Type -AssemblyName System.Drawing
    [System.Windows.Forms.Application]::EnableVisualStyles()

    $form = New-Object System.Windows.Forms.Form
    $form.Text = "Restor-PC RescueGrid"
    $form.Size = New-Object System.Drawing.Size(540, 860)
    $form.MinimumSize = New-Object System.Drawing.Size(520, 680)
    $form.StartPosition = "CenterScreen"
    $form.BackColor = [System.Drawing.Color]::FromArgb(4, 11, 20)
    $form.ForeColor = [System.Drawing.Color]::FromArgb(238, 247, 255)
    $form.Font = New-Object System.Drawing.Font("Segoe UI", 10)
    $form.AutoScroll = $true

    $y = 12
    $logoCandidates = @(
        (Join-Path $PSScriptRoot "assets\restorpc_logo.png"),
        (Join-Path $PSScriptRoot "..\..\assets\restorpc_logo.png"),
        (Join-Path $PSScriptRoot "restorpc_logo.png")
    )
    $logoPath = $logoCandidates | Where-Object { $_ -and (Test-Path -LiteralPath $_) } | Select-Object -First 1
    if ($logoPath) {
        $pic = New-Object System.Windows.Forms.PictureBox
        $pic.SizeMode = [System.Windows.Forms.PictureBoxSizeMode]::Zoom
        $pic.Location = New-Object System.Drawing.Point(24, $y)
        $pic.Size = New-Object System.Drawing.Size(200, 72)
        $pic.Image = [System.Drawing.Image]::FromFile($logoPath)
        $form.Controls.Add($pic)

        $title = New-Object System.Windows.Forms.Label
        $title.Text = "RescueGrid"
        $title.Font = New-Object System.Drawing.Font("Segoe UI", 18, [System.Drawing.FontStyle]::Bold)
        $title.ForeColor = [System.Drawing.Color]::FromArgb(0, 163, 255)
        $title.Location = New-Object System.Drawing.Point(240, 28)
        $title.Size = New-Object System.Drawing.Size(260, 40)
        $form.Controls.Add($title)
        $y = 96
    } else {
        $title = New-Object System.Windows.Forms.Label
        $title.Text = "Restor-PC RescueGrid"
        $title.Font = New-Object System.Drawing.Font("Segoe UI", 16, [System.Drawing.FontStyle]::Bold)
        $title.ForeColor = [System.Drawing.Color]::FromArgb(0, 163, 255)
        $title.Location = New-Object System.Drawing.Point(24, $y)
        $title.Size = New-Object System.Drawing.Size(480, 32)
        $form.Controls.Add($title)
        $y = 52
    }

    $mode = if (Test-IsWinPE) { "WinPE" } else { "Windows (live)" }
    $wins = @(Find-AllWindowsInstallations)
    $vols = @(Get-WinPEVolumes)
    $volLines = @(foreach ($v in $vols) {
        "{0}: {1} - {2}/{3} Go" -f $v.DriveLetter, $v.FileSystemLabel,
            [math]::Round($v.SizeRemaining / 1GB, 0), [math]::Round($v.Size / 1GB, 0)
    })
    $winTxt = if ($wins.Count) { ($wins | ForEach-Object { $_.windows_path }) -join ", " } else { "aucun" }
    $infoText = "Systeme : $mode`r`nWindows : $winTxt`r`n`r`nVolumes :`r`n" + ($volLines -join "`r`n")

    $info = New-Object System.Windows.Forms.Label
    $info.Text = $infoText
    $info.Location = New-Object System.Drawing.Point(24, $y)
    $info.AutoSize = $false
    $info.Width = 480
    $lineCount = (@($infoText -split "`r`n")).Count
    $info.Height = [Math]::Max(90, 18 * $lineCount + 12)
    $info.ForeColor = [System.Drawing.Color]::FromArgb(147, 169, 197)
    $form.Controls.Add($info)
    $y = $info.Bottom + 16

    $actions = @(
        @{ Text = "1. Diagnostic complet"; Fn = { Invoke-Diagnostic } },
        @{ Text = "2. Sauvegarde utilisateur"; Fn = { Invoke-Backup } },
        @{ Text = "3. Analyse SMART disques"; Fn = { Invoke-SMART } },
        @{ Text = "4. Reparation boot Windows"; Fn = { Invoke-BootRepair } },
        @{ Text = "5. Export rapport seul"; Fn = { Invoke-Report } },
        @{ Text = "6. Reinstallation (preparation)"; Fn = { Invoke-Reinstall } },
        @{ Text = "7. Analyser Windows hors ligne"; Fn = { Invoke-Offline } },
        @{ Text = "8. Verifier lintegrite systeme"; Fn = { Invoke-SystemCheck } },
        @{ Text = "9. Historique local (ZIP / score)"; Fn = { Show-LocalHistoryGui -BackupRoot $BackupRoot } },
        @{ Text = "10. Sync rapports vers dashboard"; Fn = { Sync-LocalZipsToDashboard -BackupRoot $BackupRoot -UploadUrl $DashboardUploadUrl -UploadApiKey $UploadApiKey } }
    )

    foreach ($a in $actions) {
        $btn = New-Object System.Windows.Forms.Button
        $btn.Text = $a.Text
        $btn.Location = New-Object System.Drawing.Point(24, $y)
        $btn.Size = New-Object System.Drawing.Size(480, 40)
        $btn.FlatStyle = "Flat"
        $btn.BackColor = [System.Drawing.Color]::FromArgb(13, 27, 47)
        $btn.ForeColor = [System.Drawing.Color]::White
        $btn.FlatAppearance.BorderColor = [System.Drawing.Color]::FromArgb(27, 54, 86)
        $fn = $a.Fn
        $btn.Add_Click({
            $form.Hide()
            try { & $fn } catch {
                [System.Windows.Forms.MessageBox]::Show("$_", "Erreur RescueGrid") | Out-Null
            }
            $form.Show()
            $form.Activate()
        }.GetNewClosure())
        $form.Controls.Add($btn)
        $y += 48
    }

    $quit = New-Object System.Windows.Forms.Button
    $quit.Text = "Quitter"
    $quit.Location = New-Object System.Drawing.Point(24, $y)
    $quit.Size = New-Object System.Drawing.Size(480, 40)
    $quit.FlatStyle = "Flat"
    $quit.BackColor = [System.Drawing.Color]::FromArgb(90, 30, 40)
    $quit.ForeColor = [System.Drawing.Color]::White
    $quit.Add_Click({ $form.Close() })
    $form.Controls.Add($quit)

    [void]$form.ShowDialog()
    if ($logoPath -and $pic -and $pic.Image) { $pic.Image.Dispose() }
}

# Entree : GUI sous Windows live (sauf -Console), menu texte sinon / WinPE.
$useGui = $Gui -or ((-not $Console) -and (-not (Test-IsWinPE)))
if ($useGui) {
    try {
        $script:RescueGridGuiMode = $true
        Show-RescueGridGui
        return
    } catch {
        Write-Host "[GUI] Impossible d'ouvrir linterface : $_" -ForegroundColor Yellow
        Write-Host "[GUI] Passage au menu texte..." -ForegroundColor Yellow
        $script:RescueGridGuiMode = $false
    }
}

# Menu principal (texte)
do {
    Show-Menu "Menu Principal"
    
    $offlineWindows = Find-AllWindowsInstallations
    $volumes = Get-WinPEVolumes
    
    if (Test-IsWinPE) {
        Write-Host " Systeme actuel : WinPE" -ForegroundColor Cyan
    } else {
        Write-Host " Systeme actuel : Windows (live)" -ForegroundColor Cyan
    }
    if ($offlineWindows.Count -gt 0) {
        Write-Host " Windows trouve(s) :" -ForegroundColor Green
        $i = 1
        foreach ($w in @($offlineWindows)) {
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
    Write-Host " 8. Verifier lintegrite systeme" -ForegroundColor White
    Write-Host " 9. Quitter" -ForegroundColor Red
    Write-Host ""
    $choice = Read-Host "Votre choix (1-9)"
    
    try {
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
            default {
                if ($choice) { Write-Host "Choix invalide." -ForegroundColor Yellow; Start-Sleep -Seconds 2 }
            }
        }
    } catch {
        Write-Host "[ERREUR] $($_.Exception.Message)" -ForegroundColor Red
        Write-Host "Appuyez sur une touche pour continuer..." -ForegroundColor Gray
        $null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")
    }
} while ($choice -ne "9")

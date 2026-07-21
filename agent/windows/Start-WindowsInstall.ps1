# Installation Windows depuis ISO / dossier setup sur la cle USB.
# ASCII only - WinPE PowerShell 5.1

function script:Find-WindowsSetupCandidates {
    $roots = @()
    foreach ($letter in 67..90 | ForEach-Object { [char]$_ }) {
        $rg = "${letter}:\RescueGrid"
        if (Test-Path "$rg\agent\windows\Start-RescueGrid.ps1") { $roots += $rg }
        if (Test-Path "${letter}:\sources\setup.exe") { $roots += "${letter}:" }
        if (Test-Path "${letter}:\setup.exe") { $roots += "${letter}:" }
    }
    $list = New-Object System.Collections.ArrayList

    foreach ($root in ($roots | Select-Object -Unique)) {
        # Dossier deja extrait
        foreach ($rel in @("windows_setup", "windows_install", "WindowsSetup", "ISO\extracted")) {
            $setup = Join-Path $root "$rel\setup.exe"
            if (Test-Path -LiteralPath $setup) {
                [void]$list.Add([pscustomobject]@{ Type = "folder"; Path = $setup; Label = "Dossier: $setup" })
            }
        }
        $setupRoot = Join-Path $root "setup.exe"
        if (Test-Path -LiteralPath $setupRoot) {
            [void]$list.Add([pscustomobject]@{ Type = "folder"; Path = $setupRoot; Label = "Dossier: $setupRoot" })
        }
        # ISO
        $isoDirs = @(
            (Join-Path $root "iso"),
            (Join-Path $root "ISO"),
            $root
        )
        foreach ($dir in $isoDirs) {
            if (-not (Test-Path $dir)) { continue }
            Get-ChildItem -LiteralPath $dir -File -Filter "*.iso" -ErrorAction SilentlyContinue | ForEach-Object {
                [void]$list.Add([pscustomobject]@{ Type = "iso"; Path = $_.FullName; Label = "ISO: $($_.Name)" })
            }
        }
    }
    return , @($list.ToArray())
}

function script:Mount-WindowsIso {
    param([string]$IsoPath)
    # Retourne la lettre du volume monte (ex: "F:") ou $null
    try {
        $img = Mount-DiskImage -ImagePath $IsoPath -PassThru -ErrorAction Stop
        Start-Sleep -Seconds 2
        $img = Get-DiskImage -ImagePath $IsoPath -ErrorAction Stop
        $vol = Get-Volume -DiskImage $img -ErrorAction SilentlyContinue | Where-Object { $_.DriveLetter } | Select-Object -First 1
        if ($vol) { return "$($vol.DriveLetter):" }
    } catch {}

    # Fallback: PowerShell Storage peut etre absent - essayer via WMI / Shell
    try {
        $shell = New-Object -ComObject Shell.Application
        $folder = $shell.NameSpace($IsoPath)
        if ($folder) {
            # Explorer mount (souvent KO en WinPE)
        }
    } catch {}
    return $null
}

function script:Dismount-WindowsIso {
    param([string]$IsoPath)
    try { Dismount-DiskImage -ImagePath $IsoPath -ErrorAction SilentlyContinue | Out-Null } catch {}
}

function script:Find-SetupExeOnDrive {
    param([string]$DriveRoot)
    $candidates = @(
        (Join-Path $DriveRoot "setup.exe"),
        (Join-Path $DriveRoot "sources\setup.exe"),
        (Join-Path $DriveRoot "Setup.exe")
    )
    foreach ($c in $candidates) {
        if (Test-Path -LiteralPath $c) { return $c }
    }
    $found = Get-ChildItem -LiteralPath $DriveRoot -Filter "setup.exe" -Recurse -ErrorAction SilentlyContinue |
        Where-Object { $_.FullName -match '\\sources\\setup\.exe$' -or $_.Directory.Name -eq $DriveRoot.TrimEnd('\') } |
        Select-Object -First 1
    if ($found) { return $found.FullName }
    $any = Get-ChildItem -LiteralPath $DriveRoot -Filter "setup.exe" -Recurse -Depth 2 -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($any) { return $any.FullName }
    return $null
}

function script:Start-WindowsSetupFromPath {
    param([string]$SetupExe)
    if (-not (Test-Path -LiteralPath $SetupExe)) {
        throw "setup.exe introuvable : $SetupExe"
    }
    $wd = Split-Path -Parent $SetupExe
    Write-Host "[SETUP] Lancement : $SetupExe" -ForegroundColor Cyan
    if (Get-Command script:Start-AppSafe -ErrorAction SilentlyContinue) {
        script:Start-AppSafe -Path $SetupExe
    } else {
        $psi = New-Object System.Diagnostics.ProcessStartInfo
        $psi.FileName = $SetupExe
        $psi.WorkingDirectory = $wd
        $psi.UseShellExecute = $true
        [void][System.Diagnostics.Process]::Start($psi)
    }
}

function script:Invoke-WindowsInstallGui {
    Add-Type -AssemblyName System.Windows.Forms
    Add-Type -AssemblyName System.Drawing

    $cands = @(script:Find-WindowsSetupCandidates)
    if ($cands.Count -eq 0) {
        [System.Windows.Forms.MessageBox]::Show(
            "Aucun ISO / setup Windows trouve.`n`nSur la cle, place :`n  RescueGrid\iso\Windows.iso`nou extrait :`n  RescueGrid\windows_setup\setup.exe`n`nPuis reessaie.",
            "Installer Windows"
        ) | Out-Null
        return
    }

    $form = New-Object System.Windows.Forms.Form
    $form.Text = "Installer Windows"
    $form.Size = New-Object System.Drawing.Size(640, 360)
    $form.StartPosition = "CenterScreen"
    $form.BackColor = [System.Drawing.Color]::FromArgb(8, 20, 38)
    $form.ForeColor = [System.Drawing.Color]::White

    $lbl = New-Object System.Windows.Forms.Label
    $lbl.Text = "Choisis l'ISO ou le dossier d'installation :"
    $lbl.Location = New-Object System.Drawing.Point(16, 16)
    $lbl.Size = New-Object System.Drawing.Size(600, 24)
    $form.Controls.Add($lbl)

    $list = New-Object System.Windows.Forms.ListBox
    $list.Location = New-Object System.Drawing.Point(16, 48)
    $list.Size = New-Object System.Drawing.Size(590, 200)
    $list.BackColor = [System.Drawing.Color]::FromArgb(13, 30, 52)
    $list.ForeColor = [System.Drawing.Color]::White
    foreach ($c in $cands) { [void]$list.Items.Add($c.Label) }
    if ($list.Items.Count -gt 0) { $list.SelectedIndex = 0 }
    $form.Controls.Add($list)

    $ok = New-Object System.Windows.Forms.Button
    $ok.Text = "Lancer setup.exe"
    $ok.Location = New-Object System.Drawing.Point(16, 270)
    $ok.Size = New-Object System.Drawing.Size(180, 36)
    $ok.BackColor = [System.Drawing.Color]::FromArgb(10, 90, 180)
    $ok.ForeColor = [System.Drawing.Color]::White
    $ok.FlatStyle = "Flat"
    $ok.Add_Click({
        if ($list.SelectedIndex -lt 0) { return }
        $sel = $cands[$list.SelectedIndex]
        try {
            if ($sel.Type -eq "folder") {
                script:Start-WindowsSetupFromPath -SetupExe $sel.Path
            } else {
                $mount = script:Mount-WindowsIso -IsoPath $sel.Path
                if (-not $mount) {
                    [System.Windows.Forms.MessageBox]::Show(
                        "Impossible de monter l'ISO en WinPE.`n`nSolution :`n1. Sous Windows, extrait l'ISO dans`n   RescueGrid\windows_setup\`n2. Verifie que setup.exe est present`n3. Relance ce bouton.",
                        "ISO"
                    ) | Out-Null
                    return
                }
                $setup = script:Find-SetupExeOnDrive -DriveRoot $mount
                if (-not $setup) {
                    script:Dismount-WindowsIso -IsoPath $sel.Path
                    [System.Windows.Forms.MessageBox]::Show("setup.exe introuvable dans l'ISO monte ($mount).", "ISO") | Out-Null
                    return
                }
                script:Start-WindowsSetupFromPath -SetupExe $setup
            }
            $form.Close()
        } catch {
            [System.Windows.Forms.MessageBox]::Show("$_", "Erreur") | Out-Null
        }
    }.GetNewClosure())
    $form.Controls.Add($ok)

    $cancel = New-Object System.Windows.Forms.Button
    $cancel.Text = "Annuler"
    $cancel.Location = New-Object System.Drawing.Point(480, 270)
    $cancel.Size = New-Object System.Drawing.Size(126, 36)
    $cancel.DialogResult = [System.Windows.Forms.DialogResult]::Cancel
    $form.Controls.Add($cancel)

    [void]$form.ShowDialog()
}

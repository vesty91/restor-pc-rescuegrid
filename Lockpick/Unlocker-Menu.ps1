# Restor-PC Unlocker - menu 64-bit (remplace Lockpick.exe x86 sous WinPE)
$ErrorActionPreference = "Continue"
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
if (-not (Test-Path (Join-Path $root "Portable\x64"))) {
    foreach ($l in 67..90 | ForEach-Object { [char]$_ }) {
        $cand = "${l}:\RescueGrid\Lockpick"
        if (Test-Path "$cand\Portable\x64") { $root = $cand; break }
    }
}
$x64 = Join-Path $root "Portable\x64"

$tools = @(
    @{ G = "Mots de passe Windows"; N = "FastBoot Detect"; P = "FastBootDetect_x64.exe" },
    @{ G = "Mots de passe Windows"; N = "Reset Hibernation"; P = "resethiberfil_x64.exe" },
    @{ G = "Mots de passe Windows"; N = "Windows Login Unlocker"; P = "WLU_x64.exe" },
    @{ G = "Mots de passe Windows"; N = "Bypass Windows Password"; P = "Bwp_x64.exe" },
    @{ G = "Mots de passe Windows"; N = "PCUnlocker"; P = "PCUnlocker_x64.exe" },
    @{ G = "Mots de passe Windows"; N = "Windows Password Reset"; P = "PassReset_x64.exe" },
    @{ G = "Mots de passe Windows"; N = "Reset Windows Password"; P = "rwp_x64.exe" },
    @{ G = "Mots de passe Windows"; N = "Active@ Password Changer"; P = "ActivePasswordChanger_x64.exe" },
    @{ G = "Mots de passe Windows"; N = "O&O BlueCon UserManager"; P = "OOStarting_x64.exe" },
    @{ G = "Mots de passe Windows"; N = "ntpwedit"; P = "ntpwedit_x64.exe" },
    @{ G = "Mots de passe Windows"; N = "PEPassPass"; P = "PEPassPass_x64.exe" },
    @{ G = "Mots de passe Windows"; N = "LazeSoft Password Recovery"; P = "UUKeys\UUKeysWindowsPasswordRecovery.exe" },
    @{ G = "Mots de passe Windows"; N = "WBG Password Recovery"; P = "WBG_PasswordKeyRecovery\Windows Password Reset.exe" },
    @{ G = "SQL Server"; N = "SQL Server Password Changer"; P = "SQLServer_x64.exe" }
)

function Start-Tool([string]$Rel) {
    $full = Join-Path $x64 $Rel
    if (-not (Test-Path -LiteralPath $full)) {
        [System.Windows.Forms.MessageBox]::Show("Fichier introuvable:`n$full", "Unlocker") | Out-Null
        return
    }
    $dir = Split-Path -Parent $full
    try {
        Start-Process -FilePath $full -WorkingDirectory $dir
    } catch {
        [System.Windows.Forms.MessageBox]::Show("Echec lancement:`n$($_.Exception.Message)", "Unlocker") | Out-Null
    }
}

$form = New-Object System.Windows.Forms.Form
$form.Text = "Restor-PC Unlocker"
$form.Size = New-Object System.Drawing.Size(520, 640)
$form.StartPosition = "CenterScreen"
$form.BackColor = [System.Drawing.Color]::FromArgb(4, 18, 40)
$form.ForeColor = [System.Drawing.Color]::White
$form.Font = New-Object System.Drawing.Font("Segoe UI", 10)
$form.MinimizeBox = $true
$form.MaximizeBox = $false
$form.FormBorderStyle = "FixedDialog"

$title = New-Object System.Windows.Forms.Label
$title.Text = "Restor-PC Unlocker"
$title.Font = New-Object System.Drawing.Font("Segoe UI", 16, [System.Drawing.FontStyle]::Bold)
$title.ForeColor = [System.Drawing.Color]::FromArgb(0, 163, 255)
$title.Location = New-Object System.Drawing.Point(16, 12)
$title.Size = New-Object System.Drawing.Size(480, 32)
$form.Controls.Add($title)

$sub = New-Object System.Windows.Forms.Label
$sub.Text = "Outils x64 - reinitialisation mots de passe (atelier)"
$sub.Location = New-Object System.Drawing.Point(18, 46)
$sub.Size = New-Object System.Drawing.Size(470, 22)
$sub.ForeColor = [System.Drawing.Color]::FromArgb(180, 200, 220)
$form.Controls.Add($sub)

$panel = New-Object System.Windows.Forms.Panel
$panel.Location = New-Object System.Drawing.Point(12, 76)
$panel.Size = New-Object System.Drawing.Size(480, 470)
$panel.AutoScroll = $true
$panel.BackColor = [System.Drawing.Color]::FromArgb(8, 28, 52)
$form.Controls.Add($panel)

$y = 8
$lastG = ""
foreach ($t in $tools) {
    if ($t.G -ne $lastG) {
        $hdr = New-Object System.Windows.Forms.Label
        $hdr.Text = $t.G
        $hdr.Font = New-Object System.Drawing.Font("Segoe UI", 10, [System.Drawing.FontStyle]::Bold)
        $hdr.ForeColor = [System.Drawing.Color]::FromArgb(120, 200, 255)
        $hdr.Location = New-Object System.Drawing.Point(8, $y)
        $hdr.Size = New-Object System.Drawing.Size(440, 24)
        $panel.Controls.Add($hdr)
        $y += 28
        $lastG = $t.G
    }
    $b = New-Object System.Windows.Forms.Button
    $b.Text = $t.N
    $b.Location = New-Object System.Drawing.Point(16, $y)
    $b.Size = New-Object System.Drawing.Size(430, 32)
    $b.FlatStyle = "Flat"
    $b.BackColor = [System.Drawing.Color]::FromArgb(0, 100, 180)
    $b.ForeColor = [System.Drawing.Color]::White
    $b.TextAlign = "MiddleLeft"
    $b.Tag = $t.P
    $b.Add_Click({
        param($s, $e)
        Start-Tool ([string]$s.Tag)
    })
    $panel.Controls.Add($b)
    $y += 38
}

$btnReboot = New-Object System.Windows.Forms.Button
$btnReboot.Text = "Redemarrer"
$btnReboot.Location = New-Object System.Drawing.Point(12, 560)
$btnReboot.Size = New-Object System.Drawing.Size(150, 34)
$btnReboot.FlatStyle = "Flat"
$btnReboot.BackColor = [System.Drawing.Color]::FromArgb(180, 100, 0)
$btnReboot.ForeColor = [System.Drawing.Color]::White
$btnReboot.Add_Click({
    $r = [System.Windows.Forms.MessageBox]::Show("Redemarrer maintenant ?", "Unlocker", "YesNo")
    if ($r -eq "Yes") {
        if (Get-Command wpeutil.exe -EA 0) { Start-Process wpeutil.exe -ArgumentList "Reboot" }
        else { shutdown.exe /r /t 0 /f }
    }
})
$form.Controls.Add($btnReboot)

$btnOff = New-Object System.Windows.Forms.Button
$btnOff.Text = "Eteindre"
$btnOff.Location = New-Object System.Drawing.Point(176, 560)
$btnOff.Size = New-Object System.Drawing.Size(150, 34)
$btnOff.FlatStyle = "Flat"
$btnOff.BackColor = [System.Drawing.Color]::FromArgb(140, 40, 40)
$btnOff.ForeColor = [System.Drawing.Color]::White
$btnOff.Add_Click({
    $r = [System.Windows.Forms.MessageBox]::Show("Eteindre maintenant ?", "Unlocker", "YesNo")
    if ($r -eq "Yes") {
        if (Get-Command wpeutil.exe -EA 0) { Start-Process wpeutil.exe -ArgumentList "Shutdown" }
        else { shutdown.exe /s /t 0 /f }
    }
})
$form.Controls.Add($btnOff)

$btnClose = New-Object System.Windows.Forms.Button
$btnClose.Text = "Fermer"
$btnClose.Location = New-Object System.Drawing.Point(342, 560)
$btnClose.Size = New-Object System.Drawing.Size(150, 34)
$btnClose.FlatStyle = "Flat"
$btnClose.BackColor = [System.Drawing.Color]::FromArgb(50, 70, 90)
$btnClose.ForeColor = [System.Drawing.Color]::White
$btnClose.Add_Click({ $form.Close() })
$form.Controls.Add($btnClose)

[void]$form.ShowDialog()

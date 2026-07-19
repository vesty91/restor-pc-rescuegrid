# Helpers GUI partages (progression, historique, signature, choix Windows, sync).
# Dot-source depuis Start-RescueGrid.ps1

function Select-WindowsInstallGui {
    param([Parameter(Mandatory)][object[]]$WindowsList)
    Add-Type -AssemblyName System.Windows.Forms
    Add-Type -AssemblyName System.Drawing
    $form = New-Object System.Windows.Forms.Form
    $form.Text = "Choisir Windows"
    $form.Size = New-Object System.Drawing.Size(480, 220)
    $form.StartPosition = "CenterScreen"
    $form.FormBorderStyle = "FixedDialog"
    $form.MaximizeBox = $false
    $form.BackColor = [System.Drawing.Color]::FromArgb(8, 20, 38)
    $form.ForeColor = [System.Drawing.Color]::White

    $lbl = New-Object System.Windows.Forms.Label
    $lbl.Text = "Plusieurs Windows detectes. Choisis celui a analyser :"
    $lbl.Location = New-Object System.Drawing.Point(20, 20)
    $lbl.Size = New-Object System.Drawing.Size(420, 36)
    $form.Controls.Add($lbl)

    $combo = New-Object System.Windows.Forms.ComboBox
    $combo.DropDownStyle = "DropDownList"
    $combo.Location = New-Object System.Drawing.Point(20, 70)
    $combo.Size = New-Object System.Drawing.Size(420, 28)
    foreach ($w in $WindowsList) {
        $label = if ($w.label) { "$($w.windows_path) ($($w.label))" } else { "$($w.windows_path)" }
        [void]$combo.Items.Add($label)
    }
    $combo.SelectedIndex = 0
    $form.Controls.Add($combo)

    $ok = New-Object System.Windows.Forms.Button
    $ok.Text = "OK"
    $ok.Location = New-Object System.Drawing.Point(240, 120)
    $ok.Size = New-Object System.Drawing.Size(100, 36)
    $ok.BackColor = [System.Drawing.Color]::FromArgb(10, 132, 255)
    $ok.ForeColor = [System.Drawing.Color]::White
    $ok.FlatStyle = "Flat"
    $ok.DialogResult = [System.Windows.Forms.DialogResult]::OK
    $form.Controls.Add($ok)
    $form.AcceptButton = $ok

    $cancel = New-Object System.Windows.Forms.Button
    $cancel.Text = "Annuler"
    $cancel.Location = New-Object System.Drawing.Point(350, 120)
    $cancel.Size = New-Object System.Drawing.Size(90, 36)
    $cancel.DialogResult = [System.Windows.Forms.DialogResult]::Cancel
    $form.Controls.Add($cancel)

    if ($form.ShowDialog() -ne [System.Windows.Forms.DialogResult]::OK) { return $null }
    return $WindowsList[$combo.SelectedIndex].windows_path
}

function Invoke-AgentWithProgress {
    param(
        [Parameter(Mandatory)][string]$AgentPath,
        [Parameter(Mandatory)][System.Collections.IList]$AgentParams,
        [string]$Title = "Diagnostic en cours..."
    )
    Add-Type -AssemblyName System.Windows.Forms
    Add-Type -AssemblyName System.Drawing

    $form = New-Object System.Windows.Forms.Form
    $form.Text = "Restor-PC RescueGrid"
    $form.Size = New-Object System.Drawing.Size(460, 160)
    $form.StartPosition = "CenterScreen"
    $form.FormBorderStyle = "FixedDialog"
    $form.ControlBox = $false
    $form.BackColor = [System.Drawing.Color]::FromArgb(8, 20, 38)
    $form.ForeColor = [System.Drawing.Color]::White

    $lbl = New-Object System.Windows.Forms.Label
    $lbl.Text = $Title
    $lbl.Location = New-Object System.Drawing.Point(20, 24)
    $lbl.Size = New-Object System.Drawing.Size(400, 28)
    $form.Controls.Add($lbl)

    $bar = New-Object System.Windows.Forms.ProgressBar
    $bar.Style = "Marquee"
    $bar.MarqueeAnimationSpeed = 30
    $bar.Location = New-Object System.Drawing.Point(20, 64)
    $bar.Size = New-Object System.Drawing.Size(400, 24)
    $form.Controls.Add($bar)

    $hint = New-Object System.Windows.Forms.Label
    $hint.Text = "Inventaire, SMART, rapport et upload..."
    $hint.ForeColor = [System.Drawing.Color]::FromArgb(147, 169, 197)
    $hint.Location = New-Object System.Drawing.Point(20, 100)
    $hint.Size = New-Object System.Drawing.Size(400, 22)
    $form.Controls.Add($hint)

    $argList = [System.Collections.Generic.List[string]]::new()
    $argList.Add("-NoProfile") | Out-Null
    $argList.Add("-ExecutionPolicy") | Out-Null
    $argList.Add("Bypass") | Out-Null
    $argList.Add("-File") | Out-Null
    $argList.Add($AgentPath) | Out-Null
    foreach ($p in $AgentParams) { $argList.Add([string]$p) | Out-Null }

    $proc = Start-Process -FilePath "powershell.exe" -ArgumentList $argList.ToArray() -PassThru -WindowStyle Minimized
    $form.Show()
    while (-not $proc.HasExited) {
        [System.Windows.Forms.Application]::DoEvents()
        Start-Sleep -Milliseconds 150
    }
    $form.Close()
    $form.Dispose()
    return $proc.ExitCode
}

function Show-ClientSignaturePad {
    param([string]$OutPath)
    Add-Type -AssemblyName System.Windows.Forms
    Add-Type -AssemblyName System.Drawing

    $state = @{
        Drawing = $false
        LastX   = 0
        LastY   = 0
        Bmp     = $null
        G       = $null
        Pen     = $null
        Pic     = $null
    }
    $state.Bmp = New-Object System.Drawing.Bitmap 580, 220
    $state.G = [System.Drawing.Graphics]::FromImage($state.Bmp)
    $state.G.SmoothingMode = "AntiAlias"
    $state.G.Clear([System.Drawing.Color]::White)
    $state.Pen = New-Object System.Drawing.Pen ([System.Drawing.Color]::Black), 2.5

    $form = New-Object System.Windows.Forms.Form
    $form.Text = "Signature client"
    $form.Size = New-Object System.Drawing.Size(640, 420)
    $form.StartPosition = "CenterScreen"
    $form.BackColor = [System.Drawing.Color]::FromArgb(8, 20, 38)
    $form.ForeColor = [System.Drawing.Color]::White

    $lbl = New-Object System.Windows.Forms.Label
    $lbl.Text = "Faites signer le client ci-dessous, puis Valider."
    $lbl.Location = New-Object System.Drawing.Point(20, 12)
    $lbl.Size = New-Object System.Drawing.Size(580, 24)
    $form.Controls.Add($lbl)

    $pic = New-Object System.Windows.Forms.PictureBox
    $pic.Location = New-Object System.Drawing.Point(20, 48)
    $pic.Size = New-Object System.Drawing.Size(580, 220)
    $pic.BorderStyle = "FixedSingle"
    $pic.Image = $state.Bmp
    $state.Pic = $pic
    $pic.Add_MouseDown({
        $state.Drawing = $true
        $state.LastX = $_.X
        $state.LastY = $_.Y
    }.GetNewClosure())
    $pic.Add_MouseUp({ $state.Drawing = $false }.GetNewClosure())
    $pic.Add_MouseMove({
        if ($state.Drawing) {
            $state.G.DrawLine($state.Pen, $state.LastX, $state.LastY, $_.X, $_.Y)
            $state.LastX = $_.X
            $state.LastY = $_.Y
            $state.Pic.Invalidate()
        }
    }.GetNewClosure())
    $form.Controls.Add($pic)

    $clear = New-Object System.Windows.Forms.Button
    $clear.Text = "Effacer"
    $clear.Location = New-Object System.Drawing.Point(20, 290)
    $clear.Size = New-Object System.Drawing.Size(100, 36)
    $clear.Add_Click({
        $state.G.Clear([System.Drawing.Color]::White)
        $state.Pic.Invalidate()
    }.GetNewClosure())
    $form.Controls.Add($clear)

    $skip = New-Object System.Windows.Forms.Button
    $skip.Text = "Passer"
    $skip.Location = New-Object System.Drawing.Point(380, 290)
    $skip.Size = New-Object System.Drawing.Size(100, 36)
    $skip.DialogResult = [System.Windows.Forms.DialogResult]::Cancel
    $form.Controls.Add($skip)

    $ok = New-Object System.Windows.Forms.Button
    $ok.Text = "Valider"
    $ok.Location = New-Object System.Drawing.Point(500, 290)
    $ok.Size = New-Object System.Drawing.Size(100, 36)
    $ok.BackColor = [System.Drawing.Color]::FromArgb(10, 132, 255)
    $ok.ForeColor = [System.Drawing.Color]::White
    $ok.FlatStyle = "Flat"
    $ok.DialogResult = [System.Windows.Forms.DialogResult]::OK
    $form.Controls.Add($ok)
    $form.AcceptButton = $ok

    $result = $form.ShowDialog()
    $saved = $null
    if ($result -eq [System.Windows.Forms.DialogResult]::OK) {
        $dir = Split-Path -Parent $OutPath
        if ($dir -and -not (Test-Path $dir)) { New-Item -ItemType Directory -Path $dir -Force | Out-Null }
        $state.Bmp.Save($OutPath, [System.Drawing.Imaging.ImageFormat]::Png)
        $saved = $OutPath
    }
    $state.G.Dispose()
    $state.Pen.Dispose()
    $state.Bmp.Dispose()
    $form.Dispose()
    return $saved
}

function Add-FileToZip {
    param([string]$ZipPath, [string]$FilePath, [string]$EntryName)
    if (-not (Test-Path $ZipPath) -or -not (Test-Path $FilePath)) { return $false }
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    try {
        $zip = [System.IO.Compression.ZipFile]::Open($ZipPath, [System.IO.Compression.ZipArchiveMode]::Update)
        $existing = $zip.GetEntry($EntryName)
        if ($existing) { $existing.Delete() }
        [System.IO.Compression.ZipFileExtensions]::CreateEntryFromFile($zip, $FilePath, $EntryName) | Out-Null
        $zip.Dispose()
        return $true
    } catch {
        return $false
    }
}

function Get-LatestInterventionFolder {
    param([string]$BackupRoot)
    if (-not $BackupRoot -or -not (Test-Path $BackupRoot)) { return $null }
    return Get-ChildItem -LiteralPath $BackupRoot -Directory -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -like "Intervention_*" } |
        Sort-Object LastWriteTime -Descending |
        Select-Object -First 1
}

function Get-LocalInterventionHistory {
    param([string]$BackupRoot, [int]$Max = 15)
    if (-not $BackupRoot -or -not (Test-Path $BackupRoot)) { return @() }
    $items = @()
    Get-ChildItem -LiteralPath $BackupRoot -Directory -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -like "Intervention_*" } |
        Sort-Object LastWriteTime -Descending |
        Select-Object -First $Max |
        ForEach-Object {
            $score = $null
            $client = ""
            $inv = Join-Path $_.FullName "inventory.json"
            if (Test-Path $inv) {
                try {
                    $j = Get-Content $inv -Raw -Encoding UTF8 | ConvertFrom-Json
                    if ($j.health) { $score = $j.health.global_score }
                    if ($j.client_name) { $client = $j.client_name }
                    elseif ($j.client -and $j.client.name) { $client = $j.client.name }
                } catch {}
            }
            $zip = "$($_.FullName).zip"
            $items += [pscustomobject]@{
                Name       = $_.Name
                Path       = $_.FullName
                ZipPath    = $(if (Test-Path $zip) { $zip } else { "" })
                Date       = $_.LastWriteTime
                Score      = $score
                ClientName = $client
            }
        }
    return $items
}

function Show-LocalHistoryGui {
    param([string]$BackupRoot)
    Add-Type -AssemblyName System.Windows.Forms
    Add-Type -AssemblyName System.Drawing
    $items = @(Get-LocalInterventionHistory -BackupRoot $BackupRoot)
    if ($items.Count -eq 0) {
        [System.Windows.Forms.MessageBox]::Show("Aucune intervention locale dans:`n$BackupRoot", "Historique") | Out-Null
        return
    }
    $form = New-Object System.Windows.Forms.Form
    $form.Text = "Historique local - RescueGrid"
    $form.Size = New-Object System.Drawing.Size(720, 420)
    $form.StartPosition = "CenterScreen"
    $form.BackColor = [System.Drawing.Color]::FromArgb(8, 20, 38)
    $form.ForeColor = [System.Drawing.Color]::White

    $list = New-Object System.Windows.Forms.ListView
    $list.View = "Details"
    $list.FullRowSelect = $true
    $list.Location = New-Object System.Drawing.Point(16, 16)
    $list.Size = New-Object System.Drawing.Size(670, 300)
    $list.BackColor = [System.Drawing.Color]::FromArgb(13, 30, 52)
    $list.ForeColor = [System.Drawing.Color]::White
    [void]$list.Columns.Add("Date", 140)
    [void]$list.Columns.Add("Client", 160)
    [void]$list.Columns.Add("Score", 70)
    [void]$list.Columns.Add("Dossier", 280)
    foreach ($it in $items) {
        $scoreTxt = if ($null -ne $it.Score) { "$($it.Score)/100" } else { "-" }
        $row = New-Object System.Windows.Forms.ListViewItem ($it.Date.ToString("dd/MM/yyyy HH:mm"))
        [void]$row.SubItems.Add("$($it.ClientName)")
        [void]$row.SubItems.Add($scoreTxt)
        [void]$row.SubItems.Add($it.Name)
        $row.Tag = $it
        [void]$list.Items.Add($row)
    }
    $form.Controls.Add($list)

    $open = New-Object System.Windows.Forms.Button
    $open.Text = "Ouvrir dossier"
    $open.Location = New-Object System.Drawing.Point(16, 330)
    $open.Size = New-Object System.Drawing.Size(140, 36)
    $open.Add_Click({
        if ($list.SelectedItems.Count -gt 0) {
            Start-Process explorer.exe $list.SelectedItems[0].Tag.Path
        }
    }.GetNewClosure())
    $form.Controls.Add($open)

    $close = New-Object System.Windows.Forms.Button
    $close.Text = "Fermer"
    $close.Location = New-Object System.Drawing.Point(560, 330)
    $close.Size = New-Object System.Drawing.Size(120, 36)
    $close.DialogResult = [System.Windows.Forms.DialogResult]::OK
    $form.Controls.Add($close)

    [void]$form.ShowDialog()
}

function Sync-LocalZipsToDashboard {
    param(
        [string]$BackupRoot,
        [string]$UploadUrl,
        [string]$UploadApiKey
    )
    Add-Type -AssemblyName System.Windows.Forms
    if (-not $UploadUrl) {
        [System.Windows.Forms.MessageBox]::Show("URL dashboard absente (rescuegrid.env).", "Sync") | Out-Null
        return
    }
    if (-not $BackupRoot -or -not (Test-Path $BackupRoot)) {
        [System.Windows.Forms.MessageBox]::Show("Dossier interventions introuvable.", "Sync") | Out-Null
        return
    }
    $zips = @(Get-ChildItem -LiteralPath $BackupRoot -Filter "Intervention_*.zip" -ErrorAction SilentlyContinue)
    if ($zips.Count -eq 0) {
        [System.Windows.Forms.MessageBox]::Show("Aucun ZIP a synchroniser.", "Sync") | Out-Null
        return
    }
    $ok = 0; $fail = 0
    foreach ($z in $zips) {
        $client = ($z.BaseName -replace '^Intervention_\d{4}-\d{2}-\d{2}_\d{6}_', '')
        if (-not $client) { $client = "Sync USB" }
        try {
            $curlArgs = @(
                "--silent", "--show-error", "--fail", "-X", "POST",
                "-F", "file=@$($z.FullName);type=application/zip",
                "-F", "client_name=$client"
            )
            if ($UploadApiKey) {
                $curlArgs += @("-F", "upload_key=$UploadApiKey", "-H", "X-Upload-Key: $UploadApiKey")
            }
            $curlArgs += $UploadUrl
            & curl.exe @curlArgs | Out-Null
            if ($LASTEXITCODE -eq 0) { $ok++ } else { $fail++ }
        } catch { $fail++ }
    }
    [System.Windows.Forms.MessageBox]::Show("Sync terminee.`nOK : $ok`nEchecs : $fail", "Sync NAS / dashboard") | Out-Null
}

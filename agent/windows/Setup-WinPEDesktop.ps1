<#
.SYNOPSIS
  Bureau Restor-PC : raccourcis sans fenetre CMD ; icones deplacables.
#>
param([switch]$NoExplorer)

$ErrorActionPreference = "Continue"
Write-Host "[Setup] Bureau Restor-PC..." -ForegroundColor Cyan

function Find-RescueGridRoot {
    foreach ($letter in 67..90 | ForEach-Object { [char]$_ }) {
        $root = "${letter}:\RescueGrid"
        if (Test-Path "$root\agent\windows\Start-RescueGrid.ps1") { return $root }
    }
    return $null
}

function Ensure-Dir([string]$Path) {
    if ($Path -and -not (Test-Path $Path)) {
        New-Item -ItemType Directory -Force -Path $Path | Out-Null
    }
}

function Clear-LinkFolder([string]$Folder) {
    if (-not $Folder -or -not (Test-Path $Folder)) { return }
    Get-ChildItem -LiteralPath $Folder -Force -ErrorAction SilentlyContinue |
        Where-Object { $_.Extension -in ".lnk", ".cmd", ".bat", ".url", ".txt", ".ps1", ".vbs" } |
        Remove-Item -Force -ErrorAction SilentlyContinue
}

function New-Lnk {
    param(
        [string]$Folder,
        [string]$Name,
        [string]$TargetPath,
        [string]$Arguments = "",
        [string]$WorkDir = "",
        [string]$IconPath = "",
        [int]$IconIndex = 0,
        [string]$WindowStyle = "1"
    )
    if (-not (Test-Path $Folder)) { return }
    if (-not $TargetPath -or -not (Test-Path -LiteralPath $TargetPath)) {
        Write-Host "  skip $Name (cible absente)" -ForegroundColor Yellow
        return
    }
    if (-not $WorkDir) { $WorkDir = Split-Path -Parent $TargetPath }
    if (-not $IconPath) { $IconPath = $TargetPath }
    $lnkPath = Join-Path $Folder ($Name + ".lnk")
    try {
        $w = New-Object -ComObject WScript.Shell
        $s = $w.CreateShortcut($lnkPath)
        $s.TargetPath = $TargetPath
        $s.Arguments = $Arguments
        $s.WorkingDirectory = $WorkDir
        $s.IconLocation = "$IconPath,$IconIndex"
        # 1=normal 3=max 7=minimized — pas de style "hidden" sur .lnk ; lanceurs PS utilisent -WindowStyle Hidden
        if ($WindowStyle -eq "7") { $s.WindowStyle = 7 }
        $s.Save()
        Write-Host "  + $Name"
    } catch {
        Write-Host "  ! $Name : $($_.Exception.Message)" -ForegroundColor Yellow
    }
}

$env:USERPROFILE = "X:\Users\Default"
$env:HOMEDRIVE = "X:"
$env:HOMEPATH = "\Users\Default"
Ensure-Dir "X:\Users\Default\Desktop"
Ensure-Dir "X:\Users\Default\AppData\Roaming\Microsoft\Windows\Start Menu\Programs"

$desktop = "X:\Users\Default\Desktop"
$startMenu = "X:\Users\Default\AppData\Roaming\Microsoft\Windows\Start Menu\Programs"
Clear-LinkFolder $desktop
Clear-LinkFolder "X:\Users\Public\Desktop"
Clear-LinkFolder $startMenu

# Icones librement deplacables (registre + WinXShell)
try {
    reg add "HKCU\Software\Microsoft\Windows\CurrentVersion\Explorer\Advanced" /v AutoArrange /t REG_DWORD /d 0 /f | Out-Null
    reg add "HKCU\Software\Microsoft\Windows\CurrentVersion\Explorer\Advanced" /v IconAutoArrange /t REG_DWORD /d 0 /f | Out-Null
    # FFlags: pas d'auto-arrange (bit0), pas d snap-to-grid (bit2) — valeur "libre"
    reg add "HKCU\Software\Microsoft\Windows\Shell\Bags\1\Desktop" /v FFlags /t REG_DWORD /d 0x00000000 /f | Out-Null
    reg add "HKCU\Software\Microsoft\Windows\Shell\Bags\1\Desktop" /v Mode /t REG_DWORD /d 1 /f | Out-Null
    reg add "HKCU\Software\Microsoft\Windows\Shell\Bags\1\Desktop" /v LogicalViewMode /t REG_DWORD /d 3 /f | Out-Null
    reg delete "HKCU\Software\Microsoft\Windows\Shell\Bags\1\Desktop" /v Sort /f 2>$null | Out-Null
    reg add "HKCU\Control Panel\Desktop" /v Wallpaper /t REG_SZ /d "X:\Windows\System32\WinXShell\wallpaper_restorpc.jpg" /f | Out-Null
    reg add "HKCU\Control Panel\Desktop" /v WallpaperStyle /t REG_SZ /d "10" /f | Out-Null
    reg add "HKCU\Software\Microsoft\Windows\CurrentVersion\Explorer\HideDesktopIcons\NewStartPanel" /v "{20D04FE0-3AEA-1069-A2D8-08002B30309D}" /t REG_DWORD /d 1 /f | Out-Null
} catch {}

$rg = Find-RescueGridRoot
Write-Host "[Setup] Cle = $rg"

$wx = Join-Path $env:SystemRoot "System32\WinXShell"
$launchers = Join-Path $wx "Launchers"
Ensure-Dir $launchers
# Nettoyer d'anciens lanceurs .cmd (qui ouvraient une console)
Get-ChildItem -LiteralPath $launchers -Force -ErrorAction SilentlyContinue |
    Where-Object { $_.Extension -in ".cmd", ".bat" } |
    Remove-Item -Force -ErrorAction SilentlyContinue
$expPlus = Join-Path $wx "Explorer++.exe"
$ps = Join-Path $env:SystemRoot "System32\WindowsPowerShell\v1.0\powershell.exe"
$cmd = Join-Path $env:SystemRoot "System32\cmd.exe"
$notepad = Join-Path $env:SystemRoot "System32\notepad.exe"
$shell32 = Join-Path $env:SystemRoot "System32\shell32.dll"

# --- Lanceurs PowerShell (aucune fenetre console) ---

$cePcPs1 = Join-Path $launchers "CePC.ps1"
@'
$e = Join-Path $env:SystemRoot "System32\WinXShell\Explorer++.exe"
if (Test-Path $e) { Start-Process -FilePath $e } else { Start-Process explorer.exe }
'@ | Set-Content $cePcPs1 -Encoding ASCII

$outilsPs1 = Join-Path $launchers "Outils.ps1"
@'
$tools = $null
foreach ($l in 67..90 | ForEach-Object { [char]$_ }) {
    $p = "${l}:\RescueGrid\tools"
    if (Test-Path $p) { $tools = $p; break }
}
if (-not $tools) {
    Add-Type -AssemblyName System.Windows.Forms -EA SilentlyContinue
    [System.Windows.Forms.MessageBox]::Show("Dossier RescueGrid\tools introuvable.", "Outils") | Out-Null
    exit 1
}
$readme = Join-Path $tools "LIRE-MOI.txt"
if (-not (Test-Path $readme)) {
    Set-Content $readme "Placez vos logiciels portables ici." -Encoding ASCII
}
$e = Join-Path $env:SystemRoot "System32\WinXShell\Explorer++.exe"
if (Test-Path $e) { Start-Process -FilePath $e -ArgumentList "`"$tools`"" }
else { Start-Process explorer.exe -ArgumentList "`"$tools`"" }
'@ | Set-Content $outilsPs1 -Encoding ASCII

$rgPs1 = Join-Path $launchers "RescueGrid.ps1"
@'
$script = $null
foreach ($l in 67..90 | ForEach-Object { [char]$_ }) {
    $p = "${l}:\RescueGrid\agent\windows\Start-RescueGrid.ps1"
    if (Test-Path $p) { $script = $p; break }
}
if (-not $script) {
    Add-Type -AssemblyName System.Windows.Forms -EA SilentlyContinue
    [System.Windows.Forms.MessageBox]::Show("RescueGrid introuvable sur la cle USB.", "RescueGrid") | Out-Null
    exit 1
}
$ps = Join-Path $env:SystemRoot "System32\WindowsPowerShell\v1.0\powershell.exe"
# Nouvelle fenetre sans console (GUI WinForms)
Start-Process -FilePath $ps -WindowStyle Hidden -ArgumentList @(
    "-NoProfile", "-STA", "-ExecutionPolicy", "Bypass", "-WindowStyle", "Hidden",
    "-File", $script, "-Gui"
)
'@ | Set-Content $rgPs1 -Encoding ASCII

$unlockPs1 = Join-Path $launchers "Unlocker.ps1"
@'
$menu = $null
$dir = $null
foreach ($l in 67..90 | ForEach-Object { [char]$_ }) {
    $p = "${l}:\RescueGrid\Lockpick\Unlocker-Menu.ps1"
    if (Test-Path $p) { $menu = $p; $dir = "${l}:\RescueGrid\Lockpick"; break }
}
if (-not $menu) {
    Add-Type -AssemblyName System.Windows.Forms -EA SilentlyContinue
    [System.Windows.Forms.MessageBox]::Show("Unlocker introuvable sur la cle.", "Unlocker") | Out-Null
    exit 1
}
$ps = Join-Path $env:SystemRoot "System32\WindowsPowerShell\v1.0\powershell.exe"
Start-Process -FilePath $ps -WorkingDirectory $dir -WindowStyle Hidden -ArgumentList @(
    "-NoProfile", "-STA", "-ExecutionPolicy", "Bypass", "-WindowStyle", "Hidden",
    "-File", $menu
)
'@ | Set-Content $unlockPs1 -Encoding ASCII

# Args communs : lanceur invisible
$psHidden = "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File"

if ($rg) {
    Ensure-Dir (Join-Path $rg "tools")
    Ensure-Dir (Join-Path $rg "Bureau")
    $readme = Join-Path $rg "tools\LIRE-MOI.txt"
    if (-not (Test-Path $readme)) {
        Set-Content $readme "Placez ici vos logiciels portables (exe).`r`nIls seront accessibles via le raccourci Outils." -Encoding ASCII
    }
}

$folders = @($desktop, $startMenu)
if ($rg) { $folders += (Join-Path $rg "Bureau") }

foreach ($folder in $folders) {
    Ensure-Dir $folder
    if ($folder -ne $desktop -and $folder -ne $startMenu) { Clear-LinkFolder $folder }

    # Ce PC : Explorer++ direct (pas de console)
    if (Test-Path $expPlus) {
        New-Lnk -Folder $folder -Name "Ce PC" -TargetPath $expPlus `
            -WorkDir $wx -IconPath $shell32 -IconIndex 15
    } else {
        New-Lnk -Folder $folder -Name "Ce PC" -TargetPath $ps `
            -Arguments "$psHidden `"$cePcPs1`"" -WorkDir $launchers -IconPath $shell32 -IconIndex 15
    }

    New-Lnk -Folder $folder -Name "Outils" -TargetPath $ps `
        -Arguments "$psHidden `"$outilsPs1`"" -WorkDir $launchers -IconPath $shell32 -IconIndex 3

    # Icone RescueGrid (priorite) :
    #   RescueGrid\RescueGrid.ico
    #   RescueGrid\agent\windows\assets\RescueGrid.ico
    #   X:\Windows\System32\WinXShell\RescueGrid.ico
    $rgIcon = $ps
    $rgIconIdx = 0
    $icoCandidates = @()
    if ($rg) {
        $icoCandidates += @(
            (Join-Path $rg "RescueGrid.ico"),
            (Join-Path $rg "agent\windows\assets\RescueGrid.ico"),
            (Join-Path $rg "agent\windows\assets\rescuegrid.ico"),
            (Join-Path $rg "agent\windows\rescuegrid.ico")
        )
    }
    $icoCandidates += (Join-Path $wx "RescueGrid.ico")
    foreach ($icoCand in $icoCandidates) {
        if ($icoCand -and (Test-Path -LiteralPath $icoCand)) {
            $rgIcon = $icoCand
            $rgIconIdx = 0
            Write-Host "  icone: $icoCand"
            break
        }
    }
    New-Lnk -Folder $folder -Name "RescueGrid" -TargetPath $ps `
        -Arguments "$psHidden `"$rgPs1`"" -WorkDir $launchers -IconPath $rgIcon -IconIndex $rgIconIdx

    $lockIcon = $shell32
    $lockIdx = 47
    if ($rg) {
        $cand = Join-Path $rg "Lockpick\Lockpick.exe"
        if (Test-Path $cand) { $lockIcon = $cand; $lockIdx = 0 }
    }
    New-Lnk -Folder $folder -Name "Unlocker" -TargetPath $ps `
        -Arguments "$psHidden `"$unlockPs1`"" -WorkDir $launchers -IconPath $lockIcon -IconIndex $lockIdx

    New-Lnk -Folder $folder -Name "Invite de commandes" -TargetPath $cmd -IconPath $cmd -IconIndex 0
    New-Lnk -Folder $folder -Name "PowerShell" -TargetPath $ps -Arguments "-NoProfile" -IconPath $ps -IconIndex 0
    New-Lnk -Folder $folder -Name "Bloc-notes" -TargetPath $notepad -IconPath $notepad -IconIndex 0
}

# Desactiver auto-arrange WinXShell si deja lance
$wxc = Join-Path $wx "WinXShellC.exe"
if (-not (Test-Path $wxc)) { $wxc = Join-Path $wx "WinXShellC_x64.exe" }
if (Test-Path $wxc) {
    try {
        & $wxc -code "Desktop:AutoArrange(0)" 2>$null | Out-Null
        & $wxc -code "Desktop:SnapToGrid(0)" 2>$null | Out-Null
        & $wxc -code "Desktop:AutoArrange(0)" 2>$null | Out-Null
        & $wxc -code "Desktop:Refresh()" 2>$null | Out-Null
        & $wxc -code "Desktop:AutoArrange(0)" 2>$null | Out-Null
        & $wxc -code "Desktop:SnapToGrid(0)" 2>$null | Out-Null
    } catch {}
}

$n = @(Get-ChildItem $desktop -Filter "*.lnk" -EA 0).Count
Write-Host "[Setup] $n raccourcis sur le bureau (sans CMD)" -ForegroundColor Green
$env:RESCUEGRID_DESKTOP_READY = "1"

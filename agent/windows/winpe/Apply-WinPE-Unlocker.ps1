# Mise a jour legere WinXShell + Setup dans boot.wim (sans re-ajouter lp.cab)
param([string]$BootWim = "E:\sources\boot.wim")
$ErrorActionPreference = "Stop"
$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = New-Object Security.Principal.WindowsPrincipal($identity)
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw "Admin requis"
}

$proj = "c:\Users\Jeux\Downloads\restor_pc_rescuegrid_v12_3_pages\v12fixed\agent\windows"
$wxSrc = Join-Path $proj "pe-shell\WinXShell"
$mount = "C:\WinPE_mount_unlocker"
$dism = "dism.exe"
Start-Transcript "C:\WinPE_unlocker.log" -Force | Out-Null

try {
    if (Test-Path $mount) {
        & $dism /Unmount-Image /MountDir:$mount /Discard 2>$null | Out-Null
        Remove-Item $mount -Recurse -Force -ErrorAction SilentlyContinue
    }
    New-Item -ItemType Directory -Force -Path $mount | Out-Null
    & $dism /Mount-Image /ImageFile:$BootWim /Index:1 /MountDir:$mount
    if ($LASTEXITCODE -ne 0) { throw "mount fail" }

    $wxDst = Join-Path $mount "Windows\System32\WinXShell"
    Copy-Item (Join-Path $wxSrc "*") $wxDst -Recurse -Force
    Copy-Item (Join-Path $proj "Setup-WinPEDesktop.ps1") (Join-Path $mount "Windows\System32\Setup-WinPEDesktop.ps1") -Force
    Copy-Item (Join-Path $proj "Setup-WinPEDesktop.ps1") "E:\RescueGrid\agent\windows\Setup-WinPEDesktop.ps1" -Force

    & $dism /Unmount-Image /MountDir:$mount /Commit
    if ($LASTEXITCODE -ne 0) { throw "commit fail" }
    Remove-Item $mount -Recurse -Force -ErrorAction SilentlyContinue
    Write-Host "OK Unlocker injecte" -ForegroundColor Green
}
catch {
    & $dism /Unmount-Image /MountDir:$mount /Discard 2>$null | Out-Null
    throw
}
finally {
    Stop-Transcript | Out-Null
}

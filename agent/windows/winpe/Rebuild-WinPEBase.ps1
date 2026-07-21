# Reconstruit un WinPE Microsoft DE BASE (ADK) puis injecte WinXShell (Strelec maison).
# Remplace boot.wim sur la cle SANS formater (garde RescueGrid\).
# Admin requis. ASCII only.
param(
    [string]$BootWim = "E:\sources\boot.wim",
    [string]$WinPERoot = "C:\WinPE",
    [switch]$SkipCopype
)

$ErrorActionPreference = "Stop"
$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = New-Object Security.Principal.WindowsPrincipal($identity)
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw "Lancer en administrateur."
}

Start-Transcript -Path "C:\WinPE_rebuild_base.log" -Force | Out-Null
try {
    . (Join-Path $PSScriptRoot "WinPE-Packages.ps1")

    $adkCandidates = @(
        "${env:ProgramFiles(x86)}\Windows Kits\10\Assessment and Deployment Kit",
        "$env:ProgramFiles\Windows Kits\10\Assessment and Deployment Kit"
    )
    $adkRoot = $adkCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1
    if (-not $adkRoot) { throw "Windows ADK + WinPE Addon introuvables." }

    $winpeDir = Join-Path $adkRoot "Windows Preinstallation Environment"
    $deployToolsDir = Join-Path $adkRoot "Deployment Tools"
    $copype = Join-Path $winpeDir "copype.cmd"
    $dandiSetEnv = Join-Path $deployToolsDir "DandISetEnv.bat"
    $ocDir = Join-Path $winpeDir "amd64\WinPE_OCs"
    $dismExe = Join-Path $deployToolsDir "amd64\DISM\dism.exe"
    if (-not (Test-Path $dismExe)) { $dismExe = "dism.exe" }

    $freshWim = Join-Path $WinPERoot "media\sources\boot.wim"
    $mountDir = Join-Path $WinPERoot "mount"

    if (-not $SkipCopype) {
        Write-Host "=== Rebuild WinPE ADK (Microsoft) ===" -ForegroundColor Cyan
        if (Test-Path $WinPERoot) {
            Write-Host "Suppression ancien $WinPERoot ..." -ForegroundColor Yellow
            if (Test-Path $mountDir) {
                & $dismExe /Unmount-Image /MountDir:"$mountDir" /Discard 2>$null | Out-Null
            }
            Remove-Item -Recurse -Force $WinPERoot -ErrorAction SilentlyContinue
            Start-Sleep 1
            if (Test-Path $WinPERoot) {
                cmd /c "rmdir /s /q `"$WinPERoot`""
            }
        }
        $copypeCmd = "call `"$dandiSetEnv`" >nul && `"$copype`" amd64 `"$WinPERoot`""
        cmd /c $copypeCmd
        if ($LASTEXITCODE -ne 0) { throw "copype a echoue ($LASTEXITCODE)" }
    }

    if (-not (Test-Path $freshWim)) { throw "boot.wim manquant apres copype : $freshWim" }

    if (Test-Path $mountDir) {
        & $dismExe /Unmount-Image /MountDir:"$mountDir" /Discard 2>$null | Out-Null
        Remove-Item $mountDir -Recurse -Force -ErrorAction SilentlyContinue
    }
    New-Item -ItemType Directory -Force -Path $mountDir | Out-Null

    Write-Host "Montage + packages ADK..." -ForegroundColor Cyan
    & $dismExe /Mount-Image /ImageFile:"$freshWim" /Index:1 /MountDir:"$mountDir"
    if ($LASTEXITCODE -ne 0) { throw "Mount echoue" }

    try {
        Add-WinPEPackages -MountDir $mountDir -OcDir $ocDir -DismExe $dismExe -Lang "fr-fr"
        Write-Host "Commit boot.wim ADK..." -ForegroundColor Cyan
        & $dismExe /Unmount-Image /MountDir:"$mountDir" /Commit
        if ($LASTEXITCODE -ne 0) { throw "Commit echoue" }
    } catch {
        & $dismExe /Unmount-Image /MountDir:"$mountDir" /Discard 2>$null | Out-Null
        throw
    }
    Remove-Item $mountDir -Recurse -Force -ErrorAction SilentlyContinue

    if (-not (Test-Path $BootWim)) {
        foreach ($l in @('E','F','G','D','H','I')) {
            if (Test-Path "${l}:\sources\boot.wim") { $BootWim = "${l}:\sources\boot.wim"; break }
        }
    }
    if (-not (Test-Path $BootWim)) { throw "Cle USB introuvable (sources\boot.wim)." }

    Write-Host "Copie boot.wim propre -> $BootWim" -ForegroundColor Cyan
    Copy-Item -Force $freshWim $BootWim

    Write-Host "Injection WinXShell (Strelec maison)..." -ForegroundColor Cyan
    & (Join-Path $PSScriptRoot "Apply-WinPE-WinXShell.ps1") -BootWim $BootWim

    Write-Host ""
    Write-Host "OK - WinPE Strelec maison pret." -ForegroundColor Green
}
finally {
    Stop-Transcript | Out-Null
}

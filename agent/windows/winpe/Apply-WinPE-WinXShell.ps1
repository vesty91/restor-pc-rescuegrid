# Injecte WinXShell (bureau type Strelec) dans boot.wim + sync cle USB.
# Admin requis. ASCII only.
param(
    [string]$BootWim = "",
    [string]$WinXShellDir = ""
)

$ErrorActionPreference = "Stop"
$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = New-Object Security.Principal.WindowsPrincipal($identity)
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw "Lancer en administrateur."
}

Start-Transcript -Path "C:\WinPE_winxshell.log" -Force | Out-Null
try {
    if (-not $WinXShellDir) {
        $WinXShellDir = Join-Path $PSScriptRoot "..\pe-shell\WinXShell"
    }
    $wxExe = Join-Path $WinXShellDir "WinXShell.exe"
    if (-not (Test-Path $wxExe)) {
        throw "WinXShell.exe introuvable : $WinXShellDir"
    }

    if (-not $BootWim -or -not (Test-Path $BootWim)) {
        foreach ($l in @('E','F','G','D','H','I')) {
            if (Test-Path "${l}:\sources\boot.wim") { $BootWim = "${l}:\sources\boot.wim"; break }
        }
    }
    if (-not $BootWim -or -not (Test-Path $BootWim)) {
        $BootWim = "C:\WinPE\media\sources\boot.wim"
    }
    if (-not (Test-Path $BootWim)) { throw "boot.wim introuvable." }

    $dism = "dism.exe"
    $mount = "C:\WinPE_mount_winx"
    if (Test-Path $mount) {
        & $dism /Unmount-Image /MountDir:"$mount" /Discard 2>$null | Out-Null
        Start-Sleep 1
        Remove-Item $mount -Recurse -Force -ErrorAction SilentlyContinue
    }
    New-Item -ItemType Directory -Force -Path $mount | Out-Null

    Write-Host "Montage $BootWim" -ForegroundColor Cyan
    & $dism /Mount-Image /ImageFile:"$BootWim" /Index:1 /MountDir:"$mount"
    if ($LASTEXITCODE -ne 0) { throw "Mount echoue" }

    try {
        $sys32 = Join-Path $mount "Windows\System32"
        $wxDst = Join-Path $sys32 "WinXShell"
        if (Test-Path $wxDst) { Remove-Item $wxDst -Recurse -Force }
        New-Item -ItemType Directory -Force -Path $wxDst | Out-Null
        Copy-Item (Join-Path $WinXShellDir "*") $wxDst -Recurse -Force
        Write-Host "WinXShell copie -> $wxDst" -ForegroundColor Green

        $setupSrc = Join-Path $PSScriptRoot "..\Setup-WinPEDesktop.ps1"
        if (Test-Path $setupSrc) {
            Copy-Item $setupSrc (Join-Path $sys32 "Setup-WinPEDesktop.ps1") -Force
        }

        # Profils / dossiers bureau
        foreach ($p in @(
            "Users\Default\Desktop",
            "Users\Public\Desktop",
            "Users\Default\AppData\Roaming\Microsoft\Windows\Start Menu\Programs",
            "ProgramData\Microsoft\Windows\Start Menu\Programs"
        )) {
            New-Item -ItemType Directory -Force -Path (Join-Path $mount $p) | Out-Null
        }

        # Wallpaper Restor-PC
        foreach ($wpName in @("wallpaper_restorpc.jpg", "wallpaper.jpg")) {
            $wp = Join-Path $wxDst $wpName
            if (Test-Path $wp) {
                Copy-Item $wp (Join-Path $mount "Users\Default\wallpaper.jpg") -Force -ErrorAction SilentlyContinue
                Copy-Item $wp (Join-Path $mount "Users\Default\wallpaper_restorpc.jpg") -Force -ErrorAction SilentlyContinue
                break
            }
        }
        # Explorer++ doit etre present a cote de WinXShell
        if (-not (Test-Path (Join-Path $wxDst "Explorer++.exe"))) {
            Write-Host "ATTENTION: Explorer++.exe manquant (Ce PC ne s'ouvrira pas)" -ForegroundColor Yellow
        }

        # IMPORTANT: une seule virgule dans winpeshl (App,Args).
        # Avec deux virgules, startnet.cmd est IGNORE -> CMD vide.
        @"
[LaunchApps]
%SYSTEMROOT%\System32\cmd.exe,/k %SYSTEMROOT%\System32\startnet.cmd
"@ | Set-Content (Join-Path $sys32 "winpeshl.ini") -Encoding ASCII

        @(
            "@echo off",
            "echo ========================================",
            "echo  Restor-PC - WinPE bureau (Strelec maison)",
            "echo ========================================",
            "echo.",
            "echo [1/4] Reseau...",
            "wpeinit",
            "echo.",
            "echo [2/4] Profil utilisateur...",
            "set USERPROFILE=X:\Users\Default",
            "set HOMEDRIVE=X:",
            "set HOMEPATH=\Users\Default",
            "if not exist X:\Users\Default\Desktop mkdir X:\Users\Default\Desktop",
            "echo.",
            "echo [3/4] Raccourcis RescueGrid...",
            "for /L %%I in (1,1,40) do (",
            "  for %%D in (C D E F G H I J K L M N O P Q R S T U V W X Y Z) do (",
            "    if exist %%D:\RescueGrid\agent\windows\Setup-WinPEDesktop.ps1 (",
            "      powershell -NoProfile -STA -ExecutionPolicy Bypass -File `"%%D:\RescueGrid\agent\windows\Setup-WinPEDesktop.ps1`" -NoExplorer",
            "      goto :shell",
            "    )",
            "  )",
            "  if exist %SystemRoot%\System32\Setup-WinPEDesktop.ps1 (",
            "    powershell -NoProfile -STA -ExecutionPolicy Bypass -File `"%SystemRoot%\System32\Setup-WinPEDesktop.ps1`" -NoExplorer",
            "    goto :shell",
            "  )",
            "  ping -n 2 127.0.0.1 >nul",
            ")",
            ":shell",
            "echo.",
            "echo [4/4] Bureau WinXShell...",
            "if exist %SystemRoot%\System32\WinXShell\WinXShell.exe (",
            "  cd /d %SystemRoot%\System32\WinXShell",
            "  start `"`" /D `"%SystemRoot%\System32\WinXShell`" WinXShell.exe -winpe",
            "  ping -n 3 127.0.0.1 >nul",
            ") else (",
            "  echo ERREUR : WinXShell.exe introuvable.",
            ")",
            "echo.",
            "echo Minimisation console session...",
            "if exist %SystemRoot%\System32\WinXShell\Minimize-PeConsole.ps1 (",
            "  powershell -NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"%SystemRoot%\System32\WinXShell\Minimize-PeConsole.ps1`"",
            ")",
            "echo Session WinPE active (fenetre minimisee)."
        ) | Set-Content (Join-Path $sys32 "startnet.cmd") -Encoding ASCII

        # Lanceur simple (secours manuel)
        @(
            "@echo off",
            "cd /d %~dp0WinXShell",
            "start `"`" /D `"%~dp0WinXShell`" WinXShell.exe -winpe"
        ) | Set-Content (Join-Path $sys32 "Launch-WinXShell.cmd") -Encoding ASCII

        # Shell registry = WinXShell (secours)
        $defaultHive = Join-Path $sys32 "config\DEFAULT"
        try {
            reg load "HKLM\WX_DEF" $defaultHive | Out-Null
            reg add "HKLM\WX_DEF\Software\Microsoft\Windows NT\CurrentVersion\Winlogon" /v Shell /t REG_SZ /d "X:\Windows\System32\WinXShell\WinXShell.exe" /f | Out-Null
            reg add "HKLM\WX_DEF\Software\Microsoft\Windows\CurrentVersion\Explorer\HideDesktopIcons\NewStartPanel" /v "{20D04FE0-3AEA-1069-A2D8-08002B30309D}" /t REG_DWORD /d 0 /f | Out-Null
            reg add "HKLM\WX_DEF\Software\Microsoft\Windows\CurrentVersion\Explorer\HideDesktopIcons\NewStartPanel" /v "{645FF040-5081-101B-9F08-00AA002F954E}" /t REG_DWORD /d 0 /f | Out-Null
            reg unload "HKLM\WX_DEF" | Out-Null
        } catch {
            try { reg unload "HKLM\WX_DEF" 2>$null | Out-Null } catch {}
        }

        Write-Host "Commit..." -ForegroundColor Cyan
        & $dism /Unmount-Image /MountDir:"$mount" /Commit
        if ($LASTEXITCODE -ne 0) { throw "Commit echoue" }
    } catch {
        & $dism /Unmount-Image /MountDir:"$mount" /Discard 2>$null | Out-Null
        throw
    }
    Remove-Item $mount -Recurse -Force -ErrorAction SilentlyContinue

    # Sync scripts + pe-shell sur cle
    $usbRoot = $null
    if ($BootWim -match "^([A-Za-z]:)\\") {
        $drive = $Matches[1]
        if (Test-Path "$drive\RescueGrid") { $usbRoot = $drive }
    }
    if (-not $usbRoot) {
        foreach ($l in @('E','F','G','D','H')) {
            if (Test-Path "${l}:\RescueGrid") { $usbRoot = "${l}:"; break }
        }
    }
    if ($usbRoot) {
        $agent = Join-Path $usbRoot "RescueGrid\agent\windows"
        $agentWinpe = Join-Path $agent "winpe"
        New-Item -ItemType Directory -Force -Path $agent, $agentWinpe | Out-Null
        $setupSrc = Join-Path $PSScriptRoot "..\Setup-WinPEDesktop.ps1"
        if (Test-Path $setupSrc) { Copy-Item $setupSrc $agent -Force }
        Copy-Item (Join-Path $PSScriptRoot "Apply-WinPE-WinXShell.ps1") $agentWinpe -Force -ErrorAction SilentlyContinue
        $peDst = Join-Path $agent "pe-shell\WinXShell"
        New-Item -ItemType Directory -Force -Path $peDst | Out-Null
        Copy-Item (Join-Path $WinXShellDir "*") $peDst -Recurse -Force
        Write-Host "Scripts sync -> $agent" -ForegroundColor Green

        # Si boot.wim etait C:\WinPE, copier aussi sur la cle
        $usbWim = Join-Path $usbRoot "sources\boot.wim"
        if ($BootWim -ne $usbWim -and (Test-Path (Split-Path $usbWim))) {
            Write-Host "Copie boot.wim -> $usbWim" -ForegroundColor Cyan
            Copy-Item -Force $BootWim $usbWim
        }
    }

    if (Test-Path "C:\WinPE\media\sources") {
        if ($BootWim -ne "C:\WinPE\media\sources\boot.wim") {
            Copy-Item -Force $BootWim "C:\WinPE\media\sources\boot.wim" -ErrorAction SilentlyContinue
        }
    }

    Write-Host ""
    Write-Host "OK - Strelec maison pret (WinXShell)." -ForegroundColor Green
    Write-Host "Redemarre sur la cle : bureau + RescueGrid." -ForegroundColor Yellow
}
finally {
    Stop-Transcript | Out-Null
}

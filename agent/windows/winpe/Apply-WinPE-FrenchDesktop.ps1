# Applique corrections bureau + pack langue FR sur boot.wim USB.
param([string]$BootWim = "E:\sources\boot.wim")
$ErrorActionPreference = "Stop"
$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = New-Object Security.Principal.WindowsPrincipal($identity)
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw "Admin requis"
}

$proj = "c:\Users\Jeux\Downloads\restor_pc_rescuegrid_v12_3_pages\v12fixed\agent\windows"
$wxSrc = Join-Path $proj "pe-shell\WinXShell"
$ocFr = "C:\Program Files (x86)\Windows Kits\10\Assessment and Deployment Kit\Windows Preinstallation Environment\amd64\WinPE_OCs\fr-fr"
$dism = "dism.exe"
$mount = "C:\WinPE_mount_frfix"
Start-Transcript "C:\WinPE_frfix.log" -Force | Out-Null

try {
    if (Test-Path $mount) {
        & $dism /Unmount-Image /MountDir:$mount /Discard 2>$null | Out-Null
        Remove-Item $mount -Recurse -Force -ErrorAction SilentlyContinue
    }
    New-Item -ItemType Directory -Force -Path $mount | Out-Null
    & $dism /Mount-Image /ImageFile:$BootWim /Index:1 /MountDir:$mount
    if ($LASTEXITCODE -ne 0) { throw "mount fail" }

    # Sync WinXShell + Setup
    $wxDst = Join-Path $mount "Windows\System32\WinXShell"
    Copy-Item (Join-Path $wxSrc "*") $wxDst -Recurse -Force
    Copy-Item (Join-Path $proj "Setup-WinPEDesktop.ps1") (Join-Path $mount "Windows\System32\Setup-WinPEDesktop.ps1") -Force
    Copy-Item (Join-Path $proj "Start-RescueGrid.ps1") "E:\RescueGrid\agent\windows\Start-RescueGrid.ps1" -Force
    Copy-Item (Join-Path $proj "Setup-WinPEDesktop.ps1") "E:\RescueGrid\agent\windows\Setup-WinPEDesktop.ps1" -Force

    # Pack langue francais
    $lp = Join-Path $ocFr "lp.cab"
    if (Test-Path $lp) {
        Write-Host "Ajout lp.cab fr-FR..."
        & $dism /Image:$mount /Add-Package /PackagePath:$lp
        foreach ($cab in @(
            "WinPE-WMI_fr-fr.cab", "WinPE-NetFx_fr-fr.cab", "WinPE-Scripting_fr-fr.cab",
            "WinPE-PowerShell_fr-fr.cab", "WinPE-StorageWMI_fr-fr.cab", "WinPE-HTA_fr-fr.cab"
        )) {
            $p = Join-Path $ocFr $cab
            if (Test-Path $p) {
                Write-Host "  + $cab"
                & $dism /Image:$mount /Add-Package /PackagePath:$p | Out-Null
            }
        }
        & $dism /Image:$mount /Set-AllIntl:fr-FR
        & $dism /Image:$mount /Set-UILang:fr-FR
        & $dism /Image:$mount /Set-SysLocale:fr-FR
        & $dism /Image:$mount /Set-UserLocale:fr-FR
        & $dism /Image:$mount /Set-InputLocale:040c:0000040c
    } else {
        Write-Host "lp.cab FR introuvable" -ForegroundColor Yellow
    }

    # startnet
    @(
        "@echo off",
        "chcp 850 >nul",
        "echo Restor-PC WinPE",
        "wpeinit",
        "set USERPROFILE=X:\Users\Default",
        "set HOMEDRIVE=X:",
        "set HOMEPATH=\Users\Default",
        "set LANG=fr_FR.UTF-8",
        "if not exist X:\Users\Default\Desktop mkdir X:\Users\Default\Desktop",
        "for /L %%I in (1,1,30) do (",
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
        "cd /d %SystemRoot%\System32\WinXShell",
        "start `"`" /D `"%SystemRoot%\System32\WinXShell`" WinXShell.exe -winpe",
        "ping -n 3 127.0.0.1 >nul",
        "if exist %SystemRoot%\System32\WinXShell\Minimize-PeConsole.ps1 (",
        "  powershell -NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"%SystemRoot%\System32\WinXShell\Minimize-PeConsole.ps1`"",
        ")",
        "echo Bureau pret"
    ) | Set-Content (Join-Path $mount "Windows\System32\startnet.cmd") -Encoding ASCII

    @"
[LaunchApps]
%SYSTEMROOT%\System32\cmd.exe,/k %SYSTEMROOT%\System32\startnet.cmd
"@ | Set-Content (Join-Path $mount "Windows\System32\winpeshl.ini") -Encoding ASCII

    & $dism /Unmount-Image /MountDir:$mount /Commit
    if ($LASTEXITCODE -ne 0) { throw "commit fail" }
    Remove-Item $mount -Recurse -Force -ErrorAction SilentlyContinue
    Write-Host "OK" -ForegroundColor Green
}
catch {
    & $dism /Unmount-Image /MountDir:$mount /Discard 2>$null | Out-Null
    throw
}
finally {
    Stop-Transcript | Out-Null
}

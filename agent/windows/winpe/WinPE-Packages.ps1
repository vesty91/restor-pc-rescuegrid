# Packages ADK WinPE (a sourcer depuis Build-RescueGridWinPE.ps1)
function Add-WinPEPackages {
    param(
        [Parameter(Mandatory)][string]$MountDir,
        [Parameter(Mandatory)][string]$OcDir,
        [string]$DismExe = "dism.exe",
        [string]$Lang = "fr-fr"
    )

    $components = @(
        "WinPE-WMI",
        "WinPE-NetFx",
        "WinPE-Scripting",
        "WinPE-PowerShell",
        "WinPE-StorageWMI",
        "WinPE-DismCmdlets",
        "WinPE-HTA",
        "WinPE-SecureStartup",
        "WinPE-EnhancedStorage",
        "WinPE-Dot3Svc",
        "WinPE-RNDIS",
        "WinPE-PPPoE",
        "WinPE-FMAPI",
        "WinPE-MDAC",
        "WinPE-FontSupport-WinRE",
        "WinPE-GamingPeripherals",
        "WinPE-WDS-Tools",
        "WinPE-WinReCfg"
    )

    foreach ($component in $components) {
        $cab = Join-Path $OcDir "$component.cab"
        if (-not (Test-Path $cab)) {
            Write-Host "  (ignore) $component" -ForegroundColor DarkYellow
            continue
        }
        Write-Host "  + $component" -ForegroundColor Gray
        & $DismExe /Image:"$MountDir" /Add-Package /PackagePath:"$cab" | Out-Null
        if ($LASTEXITCODE -ne 0) {
            throw "Echec package $component (code $LASTEXITCODE)"
        }
        foreach ($loc in @($Lang, "en-us")) {
            $langCab = Join-Path $OcDir "$loc\$component`_$loc.cab"
            if (Test-Path $langCab) {
                & $DismExe /Image:"$MountDir" /Add-Package /PackagePath:"$langCab" | Out-Null
            }
        }
    }
}

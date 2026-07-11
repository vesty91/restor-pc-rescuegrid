<#
.SYNOPSIS
  Construit automatiquement une image WinPE (boot.wim) prete pour RescueGrid.

.DESCRIPTION
  Remplace la procedure manuelle decrite dans docs/TECHNICIAN_MANUAL.md (section
  "A faire quand le Windows ADK sera installe"). Nécessite que le Windows ADK et
  son add-on WinPE soient deja installes localement (voir §4 du manuel, ou :
  winget install --id Microsoft.WindowsADK
  winget install --id Microsoft.WindowsADK.WinPEAddon

  Etapes automatisees :
  1. copype (staging du dossier de travail + copie de boot.wim) ;
  2. montage de boot.wim et ajout des composants optionnels WinPE-WMI,
     WinPE-NetFx, WinPE-Scripting, WinPE-PowerShell, WinPE-StorageWMI,
     WinPE-DismCmdlets (dans l'ordre de dependances Microsoft) ;
  3. personnalisation de startnet.cmd : detection automatique de la lettre de
     lecteur contenant RescueGrid (cle USB) et lancement de Start-RescueGrid.ps1 ;
  4. demontage/commit de boot.wim ;
  5. (optionnel, -BuildIso) generation d'une image ISO bootable via MakeWinPEMedia.

  boot.wim est produit a l'emplacement standard <WinPERoot>\media\sources\boot.wim,
  directement reutilisable par :
  - Create-RescueGridUSB.ps1 -WinPEBasePath <WinPERoot>
  - Setup-PXERescueServer.ps1 (cherche C:\WinPE\media\sources\boot.wim par defaut)

  Necessite une invite PowerShell/cmd en administrateur (montage DISM).

.PARAMETER WinPERoot
  Dossier de travail/sortie WinPE (par defaut C:\WinPE).

.PARAMETER Arch
  Architecture cible : amd64, x86, arm ou arm64 (amd64 par defaut).

.PARAMETER Force
  Supprime un dossier -WinPERoot existant avant de reconstruire.

.PARAMETER BuildIso
  Genere en plus une image ISO bootable (utilisable pour graver un DVD, monter
  en machine virtuelle, ou generer une cle USB via un autre outil).

.PARAMETER IsoPath
  Chemin de l'ISO genere si -BuildIso (par defaut <WinPERoot>\RescueGridWinPE.iso).

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File Build-RescueGridWinPE.ps1 -Force

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File Build-RescueGridWinPE.ps1 -Force -BuildIso
#>

param(
    [string]$WinPERoot = "C:\WinPE",

    [ValidateSet("amd64", "x86", "arm", "arm64")]
    [string]$Arch = "amd64",

    [switch]$Force,

    [switch]$BuildIso,

    [string]$IsoPath = ""
)

$ErrorActionPreference = "Stop"

function Test-RescueGridAdmin {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($identity)
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

if (-not (Test-RescueGridAdmin)) {
    throw "Ce script doit etre execute dans une invite PowerShell en administrateur (montage/demontage DISM requis)."
}

Write-Host "=== Build-RescueGridWinPE ===" -ForegroundColor Cyan

# 1. Localiser le Windows ADK installe localement
$adkCandidates = @(
    "${env:ProgramFiles(x86)}\Windows Kits\10\Assessment and Deployment Kit",
    "$env:ProgramFiles\Windows Kits\10\Assessment and Deployment Kit"
)
$adkRoot = $adkCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $adkRoot) {
    throw "Windows ADK introuvable. Installer d'abord : winget install --id Microsoft.WindowsADK puis winget install --id Microsoft.WindowsADK.WinPEAddon (voir docs/TECHNICIAN_MANUAL.md)."
}

$winpeDir = Join-Path $adkRoot "Windows Preinstallation Environment"
$deployToolsDir = Join-Path $adkRoot "Deployment Tools"
$copype = Join-Path $winpeDir "copype.cmd"
$makeMedia = Join-Path $winpeDir "MakeWinPEMedia.cmd"
$dandiSetEnv = Join-Path $deployToolsDir "DandISetEnv.bat"
$ocDir = Join-Path $winpeDir "$Arch\WinPE_OCs"

foreach ($required in @($copype, $makeMedia, $dandiSetEnv, $ocDir)) {
    if (-not (Test-Path $required)) {
        throw "Composant ADK manquant : $required`nL'add-on WinPE (Microsoft.WindowsADK.WinPEAddon) est-il installe pour l'architecture $Arch ?"
    }
}

Write-Host "ADK detecte : $adkRoot" -ForegroundColor Green

# 2. Preparer le dossier de travail
if (Test-Path $WinPERoot) {
    if ($Force) {
        Write-Host "Suppression de l'ancien dossier $WinPERoot..." -ForegroundColor Yellow
        Remove-Item -Recurse -Force $WinPERoot
    } else {
        throw "$WinPERoot existe deja. Relancer avec -Force pour reconstruire, ou choisir un autre -WinPERoot."
    }
}

# 3. copype : staging du dossier de travail + copie de boot.wim
Write-Host "" 
Write-Host "Etape 1/4 : copype $Arch $WinPERoot" -ForegroundColor Cyan
$copypeCmd = "call `"$dandiSetEnv`" >nul && `"$copype`" $Arch `"$WinPERoot`""
cmd /c $copypeCmd
if ($LASTEXITCODE -ne 0) {
    throw "copype a echoue (code $LASTEXITCODE). Voir la sortie ci-dessus et %WINDIR%\Logs\DISM."
}

$bootWim = Join-Path $WinPERoot "media\sources\boot.wim"
$mountDir = Join-Path $WinPERoot "mount"
if (-not (Test-Path $bootWim)) {
    throw "boot.wim non trouve apres copype : $bootWim"
}

# 4. Montage + ajout des composants optionnels WinPE
Write-Host ""
Write-Host "Etape 2/4 : montage de boot.wim et ajout PowerShell/Scripting/WMI" -ForegroundColor Cyan
$dismExe = Join-Path $deployToolsDir "$Arch\DISM\dism.exe"
if (-not (Test-Path $dismExe)) { $dismExe = "dism.exe" }

& $dismExe /Mount-Image /ImageFile:"$bootWim" /Index:1 /MountDir:"$mountDir"
if ($LASTEXITCODE -ne 0) { throw "Montage de boot.wim echoue (code $LASTEXITCODE)." }

# Ordre de dependances documente par Microsoft : WMI/NetFx/Scripting avant PowerShell,
# StorageWMI et DismCmdlets en dernier (dependent de WMI et PowerShell).
$components = @("WinPE-WMI", "WinPE-NetFx", "WinPE-Scripting", "WinPE-PowerShell", "WinPE-StorageWMI", "WinPE-DismCmdlets")
$failed = $false
$failureMessage = ""

foreach ($component in $components) {
    if ($failed) { break }

    $cab = Join-Path $ocDir "$component.cab"
    if (-not (Test-Path $cab)) {
        Write-Host "  (ignore) $component.cab absent de cet ADK" -ForegroundColor Yellow
        continue
    }

    Write-Host "  Ajout $component..." -ForegroundColor Gray
    & $dismExe /Image:"$mountDir" /Add-Package /PackagePath:"$cab" | Out-Null
    if ($LASTEXITCODE -ne 0) {
        $failed = $true
        $failureMessage = "Ajout de $component a echoue (code $LASTEXITCODE)."
        break
    }

    $langCab = Join-Path $ocDir "en-us\$component`_en-us.cab"
    if (Test-Path $langCab) {
        & $dismExe /Image:"$mountDir" /Add-Package /PackagePath:"$langCab" | Out-Null
    }
}

# 5. Personnalisation de startnet.cmd (detection automatique de la cle RescueGrid)
if (-not $failed) {
    Write-Host ""
    Write-Host "Etape 3/4 : personnalisation de startnet.cmd" -ForegroundColor Cyan
    $startnetPath = Join-Path $mountDir "Windows\System32\startnet.cmd"
    $startnetLines = @(
        "@echo off",
        "wpeinit",
        "for %%D in (C D E F G H I J K L M N O P Q R S T U V W X Y Z) do (",
        "  if exist %%D:\RescueGrid\agent\windows\Start-RescueGrid.ps1 (",
        "    powershell -ExecutionPolicy Bypass -File %%D:\RescueGrid\agent\windows\Start-RescueGrid.ps1",
        "    goto :eof",
        "  )",
        ")",
        "echo RescueGrid introuvable sur ce support - verifier la cle USB.",
        "cmd /k"
    )
    Set-Content -Path $startnetPath -Value $startnetLines -Encoding ASCII
}

# 6. Demontage : commit si succes, discard si echec (image jamais laissee incoherente)
Write-Host ""
if ($failed) {
    Write-Host "Etape 4/4 : demontage de boot.wim (annulation suite a une erreur)" -ForegroundColor Yellow
    & $dismExe /Unmount-Image /MountDir:"$mountDir" /Discard | Out-Null
    throw $failureMessage
}

Write-Host "Etape 4/4 : demontage et sauvegarde de boot.wim" -ForegroundColor Cyan
& $dismExe /Unmount-Image /MountDir:"$mountDir" /Commit | Out-Null
if ($LASTEXITCODE -ne 0) { throw "Demontage/commit de boot.wim echoue (code $LASTEXITCODE)." }

Write-Host ""
Write-Host "boot.wim pret : $bootWim" -ForegroundColor Green

# 7. Generation ISO optionnelle
if ($BuildIso) {
    if (-not $IsoPath) { $IsoPath = Join-Path $WinPERoot "RescueGridWinPE.iso" }
    Write-Host ""
    Write-Host "Generation de l'ISO bootable : $IsoPath" -ForegroundColor Cyan
    $makeMediaCmd = "call `"$dandiSetEnv`" >nul && `"$makeMedia`" /ISO `"$WinPERoot`" `"$IsoPath`""
    cmd /c $makeMediaCmd
    if ($LASTEXITCODE -ne 0) { throw "MakeWinPEMedia /ISO a echoue (code $LASTEXITCODE)." }
    Write-Host "ISO generee : $IsoPath" -ForegroundColor Green
}

Write-Host ""
Write-Host "=== Termine ===" -ForegroundColor Green
Write-Host "Utiliser ensuite :" -ForegroundColor Cyan
Write-Host "  Create-RescueGridUSB.ps1 -TargetDrive E: -WinPEBasePath $WinPERoot ..." -ForegroundColor White
Write-Host "  Setup-PXERescueServer.ps1  (reprend automatiquement C:\WinPE\media\sources\boot.wim)" -ForegroundColor White

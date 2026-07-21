<#
.SYNOPSIS
  Prepare une install Windows sur cle FAT32 RescueGrid (ISO > 4 Go).

.DESCRIPTION
  1. Monte ou extrait l'ISO Windows
  2. Decoupe install.wim / install.esd en .swm < 4 Go (limite FAT32)
  3. Copie le tout vers <cle>\RescueGrid\windows_setup\

  A lancer sous Windows (pas WinPE), de preference en administrateur.

.PARAMETER IsoPath
  Chemin du fichier .iso Windows (ex: \\Restorpc\logiciels\iso\Win11_25H2_French.iso)

.PARAMETER TargetDrive
  Lettre de la cle USB (ex: E:). Autodetect si vide.

.PARAMETER WorkDir
  Dossier temporaire de travail (defaut: %TEMP%\RescueGrid_WinSetup)

.PARAMETER KeepWorkDir
  Ne pas supprimer le dossier temporaire a la fin.

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File Prepare-WindowsSetupUSB.ps1 -IsoPath "D:\ISO\Win11.iso" -TargetDrive E:
#>
param(
    [Parameter(Mandatory = $true)]
    [string]$IsoPath,

    [string]$TargetDrive = "",

    [string]$WorkDir = "",

    [switch]$KeepWorkDir
)

$ErrorActionPreference = "Stop"

function Test-Admin {
    $p = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
    return $p.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Find-RescueGridUsb {
    foreach ($letter in @('E', 'F', 'G', 'D', 'H', 'I', 'J')) {
        $rg = "${letter}:\RescueGrid"
        if ((Test-Path "$rg\agent\windows\Start-RescueGrid.ps1") -or (Test-Path "${letter}:\sources\boot.wim")) {
            if (Test-Path $rg -or (New-Item -ItemType Directory -Force -Path $rg)) {
                return "${letter}:"
            }
        }
    }
    return $null
}

function Write-Step([string]$Msg) {
    Write-Host ""
    Write-Host "=== $Msg ===" -ForegroundColor Cyan
}

if (-not (Test-Path -LiteralPath $IsoPath)) {
    throw "ISO introuvable : $IsoPath"
}
$resolved = Resolve-Path -LiteralPath $IsoPath
$IsoPath = $resolved.ProviderPath
if (-not $IsoPath) { $IsoPath = $resolved.Path -replace '^Microsoft\.PowerShell\.Core\\FileSystem::', '' }

# Mount-DiskImage refuse souvent les chemins UNC : copie locale d'abord
$needsLocalCopy = $IsoPath.StartsWith("\\")
if ($needsLocalCopy) {
    Write-Host "ISO reseau : copie locale temporaire (plusieurs minutes)..." -ForegroundColor Yellow
    if (-not $WorkDir) {
        $WorkDir = Join-Path $env:TEMP ("RescueGrid_WinSetup_" + (Get-Date -Format "yyyyMMdd_HHmmss"))
    }
    New-Item -ItemType Directory -Force -Path $WorkDir | Out-Null
    $localIso = Join-Path $WorkDir "windows.iso"
    Write-Host "Copie : $IsoPath" -ForegroundColor DarkGray
    Write-Host "Vers  : $localIso" -ForegroundColor DarkGray
    Copy-Item -LiteralPath $IsoPath -Destination $localIso -Force
    $IsoPath = $localIso
}
$isoSizeGb = [math]::Round((Get-Item -LiteralPath $IsoPath).Length / 1GB, 2)
Write-Host "ISO pret : $IsoPath ($isoSizeGb Go)" -ForegroundColor Green

if (-not $TargetDrive) {
    $TargetDrive = Find-RescueGridUsb
}
if (-not $TargetDrive) {
    throw "Cle RescueGrid introuvable. Specifie -TargetDrive E:"
}
$TargetDrive = $TargetDrive.TrimEnd(':') + ':'
if (-not (Test-Path "$TargetDrive\")) {
    throw "Lecteur introuvable : $TargetDrive"
}

$dest = Join-Path $TargetDrive "RescueGrid\windows_setup"
Write-Host "Destination : $dest" -ForegroundColor Green

$fs = (Get-Volume -DriveLetter $TargetDrive.TrimEnd(':')).FileSystem
Write-Host "Systeme de fichiers cle : $fs" -ForegroundColor DarkGray
if ($fs -eq 'FAT32') {
    Write-Host "FAT32 detecte : split install.wim obligatoire (>4 Go)." -ForegroundColor Yellow
}

if (-not $WorkDir) {
    $WorkDir = Join-Path $env:TEMP ("RescueGrid_WinSetup_" + (Get-Date -Format "yyyyMMdd_HHmmss"))
}
New-Item -ItemType Directory -Force -Path $WorkDir | Out-Null
$extractDir = Join-Path $WorkDir "extracted"
New-Item -ItemType Directory -Force -Path $extractDir | Out-Null

$mounted = $false
$mountLetter = $null

try {
    Write-Step "1/4 Montage ou extraction de l'ISO"

    # Preferer montage (rapide) ; sinon 7z/Expand
    try {
        if (-not (Test-Admin)) {
            Write-Host "Pas admin : montage DiskImage peut echouer, tentative quand meme..." -ForegroundColor Yellow
        }
        $img = Mount-DiskImage -ImagePath $IsoPath -PassThru -ErrorAction Stop
        Start-Sleep -Seconds 2
        $vol = Get-Volume -DiskImage (Get-DiskImage -ImagePath $IsoPath) | Where-Object { $_.DriveLetter } | Select-Object -First 1
        if (-not $vol) { throw "Pas de lettre apres montage" }
        $mountLetter = "$($vol.DriveLetter):"
        $mounted = $true
        Write-Host "ISO monte sur $mountLetter" -ForegroundColor Green
        $sourceRoot = $mountLetter
    } catch {
        Write-Host "Montage impossible ($_) - extraction..." -ForegroundColor Yellow
        $sevenZip = @(
            "${env:ProgramFiles}\7-Zip\7z.exe",
            "${env:ProgramFiles(x86)}\7-Zip\7z.exe"
        ) | Where-Object { Test-Path $_ } | Select-Object -First 1

        if ($sevenZip) {
            & $sevenZip x -y "-o$extractDir" $IsoPath | Out-Null
            if ($LASTEXITCODE -ne 0) { throw "7-Zip a echoue (code $LASTEXITCODE)" }
        } else {
            # Fallback : copy via montage Shell impossible sans 7z - essayer Expand-Archive KO pour ISO
            throw "Installe 7-Zip OU relance en administrateur pour monter l'ISO."
        }
        $sourceRoot = $extractDir
        Write-Host "ISO extrait vers $extractDir" -ForegroundColor Green
    }

    $setupExe = Join-Path $sourceRoot "setup.exe"
    if (-not (Test-Path $setupExe)) {
        throw "setup.exe introuvable dans l'ISO (est-ce bien un ISO Windows ?)"
    }

    $sourcesDir = Join-Path $sourceRoot "sources"
    $wim = Join-Path $sourcesDir "install.wim"
    $esd = Join-Path $sourcesDir "install.esd"
    $imageFile = $null
    if (Test-Path $wim) { $imageFile = $wim }
    elseif (Test-Path $esd) { $imageFile = $esd }
    else {
        Write-Host "Pas de install.wim/esd trouve - copie brute." -ForegroundColor Yellow
    }

    Write-Step "2/4 Preparation des sources (split si besoin)"

    # Copier d'abord tout SAUF le gros wim/esd dans un staging
    $staging = Join-Path $WorkDir "staging"
    if (Test-Path $staging) { Remove-Item $staging -Recurse -Force }
    New-Item -ItemType Directory -Force -Path $staging | Out-Null

    Write-Host "Copie des fichiers ISO (hors install.wim/esd)..." -ForegroundColor Gray
    # robocopy tout puis on traite l'image
    & robocopy $sourceRoot $staging /E /XD "`$RECYCLE.BIN" "System Volume Information" /XF "install.wim" "install.esd" /NFL /NDL /NJH /NJS /nc /ns /np | Out-Null
    # robocopy exit codes 0-7 = ok
    if ($LASTEXITCODE -ge 8) { throw "robocopy a echoue (code $LASTEXITCODE)" }

    $stagingSources = Join-Path $staging "sources"
    New-Item -ItemType Directory -Force -Path $stagingSources | Out-Null

    if ($imageFile) {
        $imgSizeGb = [math]::Round((Get-Item $imageFile).Length / 1GB, 2)
        Write-Host "Image : $imageFile ($imgSizeGb Go)" -ForegroundColor Gray

        $needSplit = ($fs -eq 'FAT32') -or ((Get-Item $imageFile).Length -gt 3.8GB)
        if ($needSplit) {
            if (-not (Test-Admin)) {
                throw "Le split DISM necessite une invite Administrateur. Relance en admin."
            }
            $swm = Join-Path $stagingSources "install.swm"
            Write-Host "Split DISM en install.swm (morceaux ~3.8 Go)..." -ForegroundColor Yellow
            # Si ESD, convertir en WIM d'abord peut etre necessaire - DISM Split-Image marche sur WIM
            $splitSource = $imageFile
            if ($imageFile.ToLower().EndsWith(".esd")) {
                $tempWim = Join-Path $WorkDir "install_from_esd.wim"
                Write-Host "Conversion ESD -> WIM (peut etre long)..." -ForegroundColor Yellow
                & dism.exe /Export-Image /SourceImageFile:"$imageFile" /SourceIndex:1 /DestinationImageFile:"$tempWim" /Compress:max
                if ($LASTEXITCODE -ne 0) {
                    # Essayer tous les index
                    Write-Host "Export index 1 echoue, tentative index par index..." -ForegroundColor Yellow
                    $info = & dism.exe /Get-WimInfo /WimFile:"$imageFile"
                    throw "Conversion ESD echouee. Preferer un ISO avec install.wim, ou extrais manuellement."
                }
                $splitSource = $tempWim
            }
            & dism.exe /Split-Image /ImageFile:"$splitSource" /SWMFile:"$swm" /FileSize:3800
            if ($LASTEXITCODE -ne 0) { throw "DISM Split-Image a echoue (code $LASTEXITCODE)" }
            Write-Host "Split OK :" -ForegroundColor Green
            Get-ChildItem $stagingSources -Filter "install*.swm" | ForEach-Object {
                Write-Host ("  {0} ({1:N2} Go)" -f $_.Name, ($_.Length / 1GB)) -ForegroundColor Gray
            }
        } else {
            Write-Host "Copie image entiere (pas de split necessaire)..." -ForegroundColor Gray
            Copy-Item $imageFile (Join-Path $stagingSources (Split-Path $imageFile -Leaf)) -Force
        }
    }

    if (-not (Test-Path (Join-Path $staging "setup.exe"))) {
        throw "staging invalide : setup.exe manquant"
    }

    Write-Step "3/4 Copie vers la cle USB ($dest)"
    if (Test-Path $dest) {
        Write-Host "Nettoyage ancien windows_setup..." -ForegroundColor Yellow
        Remove-Item $dest -Recurse -Force
    }
    New-Item -ItemType Directory -Force -Path $dest | Out-Null
    & robocopy $staging $dest /E /NFL /NDL /NJH /NJS /nc /ns /np | Out-Null
    if ($LASTEXITCODE -ge 8) { throw "robocopy vers la cle a echoue (code $LASTEXITCODE)" }

    Write-Step "4/4 Verification"
    $checks = @(
        (Join-Path $dest "setup.exe"),
        (Join-Path $dest "sources")
    )
    foreach ($c in $checks) {
        if (Test-Path $c) { Write-Host "OK  $c" -ForegroundColor Green }
        else { Write-Host "MANQUANT  $c" -ForegroundColor Red }
    }
    $swms = @(Get-ChildItem (Join-Path $dest "sources") -Filter "install*.swm" -ErrorAction SilentlyContinue)
    $wims = @(Get-ChildItem (Join-Path $dest "sources") -Filter "install.wim" -ErrorAction SilentlyContinue)
    $esds = @(Get-ChildItem (Join-Path $dest "sources") -Filter "install.esd" -ErrorAction SilentlyContinue)
    if ($swms.Count -gt 0) {
        Write-Host ("OK  {0} fichier(s) install*.swm" -f $swms.Count) -ForegroundColor Green
    } elseif ($wims.Count -gt 0) {
        $sz = [math]::Round($wims[0].Length / 1GB, 2)
        if ($sz -gt 4 -and $fs -eq 'FAT32') {
            Write-Host "ATTENTION install.wim = $sz Go sur FAT32 (ne devrait pas arriver)" -ForegroundColor Red
        } else {
            Write-Host "OK  install.wim ($sz Go)" -ForegroundColor Green
        }
    } elseif ($esds.Count -gt 0) {
        Write-Host "OK  install.esd" -ForegroundColor Green
    } else {
        Write-Host "ATTENTION : aucune image install.* dans sources\" -ForegroundColor Yellow
    }

    Write-Host ""
    Write-Host "Termine. Boot WinPE -> Installer Windows (ISO) -> choisis windows_setup." -ForegroundColor Green
}
finally {
    if ($mounted) {
        Write-Host "Demontage ISO..." -ForegroundColor DarkGray
        try { Dismount-DiskImage -ImagePath $IsoPath -ErrorAction SilentlyContinue | Out-Null } catch {}
    }
    if (-not $KeepWorkDir -and $WorkDir -and (Test-Path $WorkDir)) {
        Write-Host "Nettoyage temp $WorkDir ..." -ForegroundColor DarkGray
        try { Remove-Item $WorkDir -Recurse -Force -ErrorAction SilentlyContinue } catch {}
    } elseif ($KeepWorkDir) {
        Write-Host "WorkDir conserve : $WorkDir" -ForegroundColor DarkGray
    }
}

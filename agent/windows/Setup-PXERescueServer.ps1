<#
.SYNOPSIS
    Restor-PC RescueGrid - PXE Rescue Server
.DESCRIPTION
    Configure un serveur PXE complet pour boot réseau :
    - DHCP (attribution IP)
    - TFTP (transfert fichiers boot)
    - HTTP (WinPE + scripts RescueGrid)
    - Menu de boot PXE personnalisé
.NOTES
    Auteur : Restor-PC RescueGrid
    Version : 1.0
    Requis : Windows Server 2012+ ou Windows 10/11 Pro
#>

param(
    [Parameter(Mandatory = $true)]
    [string]$NetworkInterface,

    [string]$PXERoot = "C:\PXERescueGrid",
    
    [string]$WinPEWim = "",
    
    [switch]$InstallDHCP,
    
    [switch]$InstallTFTP,
    
    [switch]$InstallHTTP
)

$ErrorActionPreference = "Continue"
$host.UI.RawUI.WindowTitle = "Restor-PC RescueGrid - PXE Rescue Server"

function Write-Step {
    param([string]$Text, [string]$Color = "Cyan")
    Write-Host ""
    Write-Host "=============================================" -ForegroundColor $Color
    Write-Host "   $Text" -ForegroundColor $Color
    Write-Host "=============================================" -ForegroundColor $Color
    Write-Host ""
}

function Test-Admin {
    $currentPrincipal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
    return $currentPrincipal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

# Verifications
if (-not (Test-Admin)) {
    Write-Host "[ERREUR] Ce script doit etre execute en tant qu'administrateur." -ForegroundColor Red
    pause
    exit 1
}

$nic = Get-NetAdapter -Name $NetworkInterface -ErrorAction SilentlyContinue
if (-not $nic) {
    Write-Host "[ERREUR] Interface reseau '$NetworkInterface' introuvable." -ForegroundColor Red
    Write-Host "Interfaces disponibles :" -ForegroundColor Yellow
    Get-NetAdapter | Where-Object { $_.Status -eq "Up" } | ForEach-Object { Write-Host "  - $($_.Name)" -ForegroundColor Gray }
    pause
    exit 1
}

Write-Step "PXE Rescue Server - Interface: $($nic.Name)" "Cyan"

# Creer la structure de dossiers
Write-Step "Etape 1/5 : Structure PXE" "Cyan"
$folders = @(
    "$PXERoot",
    "$PXERoot\Boot",
    "$PXERoot\Scripts",
    "$PXERoot\WinPE",
    "$PXERoot\Tools",
    "$PXERoot\Tools\smartctl",
    "$PXERoot\Tools\RecoveryTools",
    "$PXERoot\Tools\Docs"
)
foreach ($folder in $folders) {
    New-Item -ItemType Directory -Path $folder -Force | Out-Null
    Write-Host "  -> $folder" -ForegroundColor Green
}

# Etape 2 : WinPE
Write-Step "Etape 2/5 : WinPE" "Cyan"
$winpeSource = ""
if ($WinPEWim -and (Test-Path $WinPEWim)) {
    $winpeSource = $WinPEWim
}
else {
    # Chercher WinPE dans les emplacements standards
    $winpePaths = @(
        "C:\WinPE\media\sources\boot.wim",
        "C:\Program Files (x86)\Windows Kits\10\Assessment and Deployment Kit\Windows Preinstallation Environment\amd64\en-us\winpe.wim",
        "$PXERoot\WinPE\boot.wim"
    )
    foreach ($path in $winpePaths) {
        if (Test-Path $path) {
            $winpeSource = $path
            break
        }
    }
}

if ($winpeSource) {
    Copy-Item $winpeSource "$PXERoot\Boot\boot.wim" -Force
    Write-Host "  -> WinPE copie depuis $winpeSource" -ForegroundColor Green
}
else {
    Write-Host "  -> WinPE non trouve. Copier boot.wim manuellement dans $PXERoot\Boot\" -ForegroundColor Yellow
    Write-Host "     Telecharger ADK : https://learn.microsoft.com/fr-fr/windows-hardware/get-started/adk-install" -ForegroundColor Gray
}

# Etape 3 : Scripts RescueGrid
Write-Step "Etape 3/5 : Scripts RescueGrid" "Cyan"
$scriptSource = Split-Path -Parent $MyInvocation.MyCommand.Path
$scripts = @("Invoke-RescueGrid.ps1", "Start-RescueGrid.ps1")
foreach ($script in $scripts) {
    $src = Join-Path $scriptSource $script
    if (Test-Path $src) {
        Copy-Item $src "$PXERoot\Scripts\" -Force
        Write-Host "  -> $script copie" -ForegroundColor Green
    }
}

# Etape 4 : Configuration TFTP
Write-Step "Etape 4/5 : Serveur TFTP" "Cyan"
if ($InstallTFTP) {
    Write-Host "  Installation du serveur TFTP Windows..." -ForegroundColor Yellow
    # Windows inclut un serveur TFTP optionnel
    $tftpPath = "$PXERoot\TFTP"
    New-Item -ItemType Directory -Path $tftpPath -Force | Out-Null
    
    # Copier les fichiers de boot
    if (Test-Path "$PXERoot\Boot\boot.wim") {
        Copy-Item "$PXERoot\Boot\boot.wim" $tftpPath -Force
        Write-Host "  -> boot.wim copie dans TFTP" -ForegroundColor Green
    }
    
    Write-Host "  -> Serveur TFTP pret dans $tftpPath" -ForegroundColor Green
    Write-Host "  -> Configurer le routeur/switch pour rediriger le port 69 UDP vers ce serveur" -ForegroundColor Yellow
}
else {
    Write-Host "  TFTP ignore (utiliser -InstallTFTP pour l'activer)" -ForegroundColor Gray
}

# Etape 5 : Configuration HTTP
Write-Step "Etape 5/5 : Serveur HTTP (IIS ou Python)" "Cyan"
if ($InstallHTTP) {
    Write-Host "  Installation d'IIS..." -ForegroundColor Yellow
    # Installer IIS si absent
    $iis = Get-WindowsFeature -Name Web-Server -ErrorAction SilentlyContinue
    if (-not $iis.Installed) {
        Install-WindowsFeature -Name Web-Server -IncludeManagementTools | Out-Null
        Write-Host "  -> IIS installe" -ForegroundColor Green
    }
    
    # Creer le site PXE
    $siteName = "PXERescueGrid"
    $sitePath = $PXERoot
    if (-not (Get-IISSite -Name $siteName -ErrorAction SilentlyContinue)) {
        New-IISSite -Name $siteName -PhysicalPath $sitePath -BindingInformation "*:8080:" | Out-Null
        Write-Host "  -> Site IIS cree : http://$($nic.IPv4Address.IPAddress):8080" -ForegroundColor Green
    }
    
    # Ajouter les types MIME pour WIM
    Add-WebConfigurationProperty -Filter "//staticContent" -Name "." -Value @{fileExtension=".wim"; mimeType="application/octet-stream"} -ErrorAction SilentlyContinue | Out-Null
    Add-WebConfigurationProperty -Filter "//staticContent" -Name "." -Value @{fileExtension=".ps1"; mimeType="application/x-powershell"} -ErrorAction SilentlyContinue | Out-Null
}
else {
    Write-Host "  HTTP ignore (utiliser -InstallHTTP pour IIS)" -ForegroundColor Gray
    Write-Host "  Alternative: lancer un serveur Python simple :" -ForegroundColor Yellow
    Write-Host "    cd $PXERoot" -ForegroundColor Gray
    Write-Host "    python -m http.server 8080" -ForegroundColor Gray
}

# Creer le menu PXE
Write-Step "Menu PXE" "Cyan"
$pxeMenu = @"
DEFAULT menu.c32
PROMPT 0
TIMEOUT 30

MENU TITLE Restor-PC RescueGrid - Boot Reseau
LABEL local
  MENU LABEL ^Boot local (disque dur)
  LOCALBOOT 0

LABEL winpe
  MENU LABEL ^WinPE RescueGrid (diagnostic + recuperation)
  KERNEL pxeboot.0
  APPEND boot.wim

LABEL winpe_safe
  MENU LABEL WinPE ^Mode sans echec (reseau seul)
  KERNEL pxeboot.0
  APPEND boot.wim /safeboot
"@
$pxeMenu | Out-File -FilePath "$PXERoot\Boot\pxelinux.cfg\default" -Encoding ascii -Force
Write-Host "  -> Menu PXE cree" -ForegroundColor Green

# Resume
Write-Step "Configuration terminee !" "Green"
Write-Host "Dossier PXE : $PXERoot" -ForegroundColor White
Write-Host ""
Write-Host "Structure :" -ForegroundColor Cyan
Write-Host "  $PXERoot\" -ForegroundColor Gray
Write-Host "    Boot\" -ForegroundColor Gray
Write-Host "      boot.wim              <- WinPE" -ForegroundColor Gray
Write-Host "      pxelinux.cfg\default  <- Menu PXE" -ForegroundColor Gray
Write-Host "    Scripts\" -ForegroundColor Gray
Write-Host "      Invoke-RescueGrid.ps1" -ForegroundColor Gray
Write-Host "      Start-RescueGrid.ps1" -ForegroundColor Gray
Write-Host "    Tools\" -ForegroundColor Gray
Write-Host "      smartctl\" -ForegroundColor Gray
Write-Host "      RecoveryTools\" -ForegroundColor Gray
Write-Host "      Docs\" -ForegroundColor Gray
Write-Host ""
Write-Host "Prochaines etapes :" -ForegroundColor Yellow
Write-Host "  1. Copier boot.wim dans $PXERoot\Boot\ (si ADK installe)" -ForegroundColor White
Write-Host "  2. Configurer le serveur DHCP/TFTP pour pointer vers ce serveur" -ForegroundColor White
Write-Host "  3. Configurer le routeur : ip helper-address <IP_SERVEUR_PXE>" -ForegroundColor White
Write-Host "  4. Tester le boot PXE sur un client" -ForegroundColor White
Write-Host "  5. Dans WinPE, lancer : X:\Scripts\Start-RescueGrid.ps1" -ForegroundColor Cyan
Write-Host ""
pause
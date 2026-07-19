# Manuel technicien — Clé USB RescueGrid / WinPE / PXE

Ce manuel remplace les références à `README_LANCEMENT.md` /
`TECHNICIAN_MANUAL.md` mentionnées par l'ancien `Build-RescueGridUSB.ps1`
(absents du dépôt jusqu'ici). Depuis v12.3, **un seul script** construit la
clé USB technicien : `Create-RescueGridUSB.ps1` (`Build-RescueGridUSB.ps1`
reste disponible mais n'est plus qu'un alias de compatibilité qui le redirige).

## 1. Construire la clé USB

Depuis `agent\windows\`, en PowerShell (administrateur requis si `-Format`) :

```powershell
powershell -ExecutionPolicy Bypass -File Create-RescueGridUSB.ps1 `
    -TargetDrive E: `
    -DashboardUrl "http://192.168.1.10:8000" `
    -IncludeProject
```

Options utiles :

| Paramètre | Effet |
|---|---|
| `-Format` | Formate la clé (confirmation "FORMAT" requise) — **efface toutes les données** |
| `-FileSystem NTFS\|FAT32` | Système de fichiers si `-Format` (NTFS par défaut ; FAT32 si compatibilité BIOS/UEFI ancien requise) |
| `-DashboardUrl` | URL du dashboard écrite dans `config\rescuegrid.env`, relue automatiquement par l'agent |
| `-UploadApiKey` | Clé d'API upload, écrite dans `config\rescuegrid.env` |
| `-IncludeProject` | Copie le projet complet (hors `.git`, `.venv`, `storage`, bases `.db`) |
| `-WinPEBasePath` | Dossier ADK local pour copier `boot.wim` si disponible (voir §4) |
| `-SmartctlSource`, `-TestDiskSource` | Dossiers contenant les binaires à copier dans `tools\smartctl` / `tools\testdisk` |

À l'issue, la clé contient :

```
E:\Start-RescueGrid.cmd          <- lanceur Windows
E:\README_USB.txt
E:\RescueGrid\
    agent\windows\Invoke-RescueGrid.ps1
    agent\windows\Start-RescueGrid.ps1
    config\rescuegrid.env         <- config auto-chargée (URL dashboard, dossiers)
    reports\ backup\ blackbox\
    tools\smartctl\ tools\testdisk\ tools\photorec\
    winpe\startnet.cmd
    winpe\boot.wim                 <- si ADK installé (voir §4)
```

## 2. Utilisation sur un poste Windows fonctionnel

1. Brancher la clé sur le PC client.
2. Ouvrir `Start-RescueGrid.cmd` **en administrateur**.
3. Choisir une option du menu (diagnostic, sauvegarde, SMART, réparation boot...).
4. Les rapports/ZIP sont écrits dans le dossier configuré (`RESCUEGRID_BACKUP_ROOT`
   dans `config\rescuegrid.env`, pré-rempli automatiquement).

## 3. Utilisation en WinPE (PC qui ne démarre plus)

1. Intégrer `RescueGrid\winpe\startnet.cmd` dans votre image WinPE (voir §4
   si vous n'avez pas encore construit d'image).
2. Démarrer le PC client sur la clé USB (menu boot / F12 selon le fabricant).
3. `startnet.cmd` lance automatiquement `Start-RescueGrid.ps1` depuis la
   première lettre de lecteur où `RescueGrid\agent\windows\Start-RescueGrid.ps1`
   est trouvé.
4. Le menu WinPE (diagnostic, sauvegarde, SMART, réparation boot, export
   rapport, préparation réinstallation, analyse hors ligne, vérification
   intégrité, quitter) fonctionne à l'identique du mode Windows.
5. **Clé bootable complète** : après ADK (§4), lancer
   `Create-RescueGridUSB.ps1 -TargetDrive E: -WinPEBasePath C:\WinPE`
   (adapte la lettre). Sans `boot.wim`, la clé reste utilisable en Windows
   live via `Start-RescueGrid.cmd` (GUI : progression, historique ZIP, sync
   dashboard, signature client).

## 4. Construire l'image WinPE avec `Build-RescueGridWinPE.ps1`

Depuis v12.3.1, le pipeline ADK est automatisé et **validé réellement**
(build effectué et vérifié : `boot.wim` ~480 Mo avec PowerShell/Scripting
intégrés, ISO ~535 Mo générée avec succès).

### 4.1 Installer le Windows ADK (une seule fois)

```powershell
winget install --id Microsoft.WindowsADK --silent --accept-package-agreements --accept-source-agreements
winget install --id Microsoft.WindowsADK.WinPEAddon --silent --accept-package-agreements --accept-source-agreements
```

Nécessite une invite **administrateur** (chaque commande installe ~1 Go de
composants ; compter 10-20 minutes selon la connexion). Alternative : les
installeurs graphiques sont disponibles sur la
[page officielle Microsoft ADK](https://learn.microsoft.com/fr-fr/windows-hardware/get-started/adk-install).

### 4.2 Construire `boot.wim` (+ ISO optionnelle)

Depuis `agent\windows\`, en PowerShell **administrateur** (le montage/démontage
DISM le requiert) :

```powershell
powershell -ExecutionPolicy Bypass -File Build-RescueGridWinPE.ps1 -Force -BuildIso
```

Le script :
1. Lance `copype amd64 C:\WinPE` (staging + copie de `boot.wim`) ;
2. Monte `boot.wim` et ajoute dans l'ordre les composants optionnels
   `WinPE-WMI`, `WinPE-NetFx`, `WinPE-Scripting`, `WinPE-PowerShell`,
   `WinPE-StorageWMI`, `WinPE-DismCmdlets` (ordre de dépendances Microsoft) ;
3. Personnalise `startnet.cmd` : détection automatique de la première lettre
   de lecteur contenant `RescueGrid\agent\windows\Start-RescueGrid.ps1` et
   lancement automatique du menu ;
4. Démonte et sauvegarde `boot.wim` (ou annule proprement — `/Discard` — en
   cas d'erreur à une étape) ;
5. Si `-BuildIso` : génère `C:\WinPE\RescueGridWinPE.iso` via `MakeWinPEMedia /ISO`
   (utilisable en VM, gravure DVD, ou un autre outil de création de clé).

Paramètres : `-WinPERoot` (défaut `C:\WinPE`), `-Arch` (`amd64`/`x86`/`arm`/`arm64`),
`-Force` (reconstruit un dossier existant), `-BuildIso`, `-IsoPath`.

Raccourci équivalent : `start_build_winpe.bat` à la racine du projet (à lancer
en administrateur — clic droit → Exécuter en tant qu'administrateur).

### 4.3 Copier `boot.wim` sur la clé USB technicien

```powershell
powershell -ExecutionPolicy Bypass -File Create-RescueGridUSB.ps1 -TargetDrive E: -WinPEBasePath C:\WinPE
```

`Create-RescueGridUSB.ps1` copie automatiquement `C:\WinPE\media\sources\boot.wim`
vers `RescueGrid\winpe\boot.wim` sur la clé (voir §1).

### 4.4 Rendre la clé réellement bootable (hors script)

La copie de `boot.wim` sur la clé (§4.3) suffit pour le PXE (§5) et pour une
image ISO montée en VM. Pour une clé USB **bootable en BIOS/UEFI direct**,
il faut en plus déployer les fichiers de démarrage générés par `copype` dans
`C:\WinPE\media` (dossiers `Boot`, `EFI`, `bootmgr`...) sur la clé, ou utiliser
`MakeWinPEMedia /UFD C:\WinPE E:` (efface la clé et la rend bootable en une
commande, disponible avec l'ADK) — cette dernière option écrase toute donnée
existante sur `E:` et n'est pas appelée automatiquement par ce projet pour
éviter une perte de données accidentelle.

## 5. Serveur PXE (boot réseau, sans clé USB)

```powershell
powershell -ExecutionPolicy Bypass -File Setup-PXERescueServer.ps1
```

Prépare l'arborescence et le menu `pxelinux` sous `C:\PXERescueGrid`. Les
services TFTP/DHCP eux-mêmes restent à installer/configurer manuellement
(non automatisé) — voir les instructions affichées par le script.

## 6. Consignes de sécurité (rappel)

- Ne jamais lancer de réparation disque (`CHKDSK /F`, `bootrec`, formatage)
  avant d'avoir obtenu une sauvegarde/image si le SMART du disque est
  critique — risque de perte de données.
- Conserver les dossiers `reports`, `blackbox` et `backup` produits par
  l'agent comme preuves d'intervention (horodatage, inventaire, actions_log).
- Le consentement client doit être recueilli avant toute collecte de données,
  y compris en usage silencieux planifié (voir
  [BACKUP_PLANIFIE.md](BACKUP_PLANIFIE.md)).

## 7. Dépannage rapide

| Symptôme | Cause probable | Action |
|---|---|---|
| "Invoke-RescueGrid.ps1 introuvable" dans `Start-RescueGrid.ps1` | Clé mal copiée ou lettre de lecteur différente en WinPE | Vérifier `RescueGrid\agent\windows\` sur la clé |
| Upload échoue (`401`) | `UPLOAD_API_KEY` serveur configurée mais absente côté agent | Renseigner `-UploadApiKey` ou `RESCUEGRID_UPLOAD_API_KEY` dans `rescuegrid.env` |
| `smartctl` indisponible sous WinPE | Binaire non copié sur la clé | Copier `smartctl.exe`/`.dll` dans `RescueGrid\tools\smartctl\` (voir `Install-RescueGridTools.ps1` pour la copie côté Windows) |

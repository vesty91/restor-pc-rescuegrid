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
4. Le menu WinPE (9 options : diagnostic, sauvegarde, SMART, réparation boot,
   export rapport, préparation réinstallation, analyse hors ligne, vérification
   intégrité, quitter) fonctionne à l'identique du mode Windows.

## 4. À faire quand le Windows ADK sera installé (reporté)

Le Windows ADK + add-on WinPE n'est pas encore installé sur ce poste de
build (situation au moment de la rédaction). Une fois disponible :

1. Installer [Windows ADK](https://learn.microsoft.com/fr-fr/windows-hardware/get-started/adk-install)
   puis l'add-on **WinPE**.
2. Construire un environnement WinPE de base (`copype amd64 C:\WinPE`),
   personnaliser si besoin (pilotes réseau/stockage additionnels via
   `Add-WindowsDriver`, ajout PowerShell via les Optional Components WinPE-
   PowerShell/WinPE-NetFx/WinPE-Scripting/WinPE-WMI — requis pour exécuter
   les scripts `.ps1` de ce projet sous WinPE).
3. Relancer `Create-RescueGridUSB.ps1 -TargetDrive E: -WinPEBasePath C:\WinPE`
   pour copier `boot.wim` sur la clé (`RescueGrid\winpe\boot.wim`).
4. Rendre la clé réellement bootable (`bootsect`/`diskpart` + copie de
   `boot.wim` en tant qu'image de démarrage, ou génération d'une ISO avec
   `MakeWinPEMedia /ISO`) — cette étape de "bootabilisation" n'est pas
   automatisée par ce projet et reste à dérouler manuellement selon la
   procédure Microsoft standard.

Ce pipeline de build ADK complet n'est volontairement pas scripté dans ce
lot (ADK non disponible pour test au moment de l'écriture) — à reprendre
lorsque l'environnement de build sera prêt.

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

# Restor-PC RescueGrid v6.0 — Atelier/Synology + USB Builder

Cette version ajoute une couche produit orientée atelier :

- Dashboard UX compact avec KPI métier.
- Import ZIP RescueGrid mis en avant.
- Alertes disque/tickets visibles dès l'accueil.
- Recherche globale renforcée.
- Page `/tools` pour USB/PXE/Synology.
- Créateur de clé USB technicien : `agent/windows/Create-RescueGridUSB.ps1`.
- Lanceur : `start_usb_builder.bat`.

## Démarrage dashboard

```powershell
powershell -ExecutionPolicy Bypass -File install_dependencies.ps1
.\start_dashboard.bat
```

Ouvrir :

```txt
http://localhost:8000
```

Compte par défaut si non modifié :

```txt
admin / rescuegrid2026
```

## Créer une clé USB RescueGrid

Brancher une clé USB puis lancer :

```powershell
.\start_usb_builder.bat
```

ou en manuel :

```powershell
powershell -ExecutionPolicy Bypass -File agent\windows\Create-RescueGridUSB.ps1 `
  -TargetDrive E: `
  -DashboardUrl "http://192.168.1.10:8000" `
  -IncludeProject
```

Le script crée :

```txt
E:\
├── Start-RescueGrid.cmd
├── README_USB.txt
└── RescueGrid\
    ├── agent\windows\
    │   ├── Invoke-RescueGrid.ps1
    │   └── Start-RescueGrid.ps1
    ├── config\rescuegrid.env
    ├── reports\
    ├── backup\
    ├── blackbox\
    ├── tools\
    └── winpe\startnet.cmd
```

## Utilisation clé USB

### Depuis Windows

```txt
1. Ouvrir la clé USB.
2. Clic droit sur Start-RescueGrid.cmd.
3. Exécuter en administrateur.
4. Choisir diagnostic, sauvegarde, SMART, rapport ou upload NAS.
```

### Depuis WinPE

Le script prépare `RescueGrid\winpe\startnet.cmd`.

À intégrer dans ton image WinPE si tu veux un démarrage automatique du menu RescueGrid.

## Notes importantes

- Le script USB Builder ne télécharge pas automatiquement Windows ADK.
- Il ne formate pas la clé sans `-Format`.
- Les outils externes `smartctl`, `TestDisk`, `PhotoRec`, `ddrescue` restent à fournir selon ton environnement.
- Pour ddrescue, privilégier un environnement Linux Rescue ou PXE Linux.

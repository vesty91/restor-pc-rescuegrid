# Restor-PC RescueGrid v9.2

> Plateforme technicien pour diagnostic PC, sauvegarde, récupération professionnelle et suivi d'interventions.

## Démarrage rapide

```batch
start_dashboard.bat      ← Dashboard web (http://localhost:8000)
start_agent.bat          ← Agent rapide
start_agent_windows.bat  ← Menu technicien (8 options)
start_winpe_menu.bat     ← WinPE Atelier
```

**Login dashboard** : `admin` / `rescuegrid2026` (à changer via `ADMIN_PASSWORD` dans `.env`)

## Fonctionnalités principales

### Agent Windows (PowerShell)
- Diagnostic complet : BIOS, CPU, RAM, GPU, disques, SMART (NVMe/SATA/USB)
- Score santé 0–100 avec séparation SMART matériel / anomalies NTFS
- Sauvegarde profil utilisateur (complet ou dossiers essentiels)
- Mode Windows hors ligne / WinPE
- Récupération : ddrescue, TestDisk, PhotoRec (natif ou WSL)
- Rapport HTML, BlackBox JSON, manifeste SHA256, archive ZIP
- Upload automatique vers le dashboard

### Dashboard Web (FastAPI)
- Authentification JWT + rôles admin / technicien
- Gestion : interventions, clients, machines, pièces, factures, tickets
- Import ZIP sécurisé (anti-ZipSlip, limites configurables)
- Téléchargements : rapport, ZIP, manifeste cryptographique
- Recherche globale, export Excel, étiquettes imprimables
- KPI atelier : alertes disque, tickets ouverts, CA du mois

### Déploiement
- **Local** : SQLite + `start_dashboard.bat`
- **Production NAS** : `docker-compose.synology.yml` (PostgreSQL, MinIO, Nginx, pgAdmin)

## Commandes essentielles

```powershell
# Diagnostic + ZIP
powershell -ExecutionPolicy Bypass -File agent\windows\Invoke-RescueGrid.ps1 -ClientName "Dupont" -BackupRoot "E:\RestorPC" -CreateZip

# Sauvegarde avant réinstallation
powershell -ExecutionPolicy Bypass -File agent\windows\Invoke-RescueGrid.ps1 -ClientName "Dupont" -BackupRoot "E:\RestorPC" -UserProfilePath "C:\Users\Dupont" -BackupEssentialFoldersOnly -CreateZip

# Upload vers dashboard (avec clé API si configurée)
powershell -ExecutionPolicy Bypass -File agent\windows\Invoke-RescueGrid.ps1 -ClientName "Dupont" -BackupRoot "E:\RestorPC" -CreateZip -DashboardUploadUrl "http://localhost:8000/upload" -UploadApiKey "votre-cle"
```

## Structure du projet

```
restor_pc_rescuegrid/
├── agent/windows/          ← Agent PowerShell + scripts USB/WinPE/PXE
├── backend/                ← API FastAPI + templates HTML
├── docs/                   ← Documentation atelier
├── nginx/                  ← Config reverse proxy (Synology)
├── docker-compose.yml      ← Déploiement local
└── start_*.bat             ← Lanceurs Windows
```

## Documentation

| Document | Description |
|----------|-------------|
| [Démarrage rapide](DEMARRAGE_RAPIDE.md) | Installation et premiers pas |
| [Guide de lancement](README_LANCEMENT.md) | Commandes détaillées |
| [Déploiement](README_DEPLOIEMENT.md) | Docker, NAS, configuration |
| [Manuel technicien](docs/TECHNICIAN_MANUAL.md) | Workflow et dépannage |
| [Architecture](docs/ARCHITECTURE.md) | Architecture technique |
| [Roadmap](docs/ROADMAP.md) | Feuille de route |
| [Changelog](CHANGELOG.md) | Historique des versions |

## Sécurité (production)

1. Changer `SECRET_KEY` et `ADMIN_PASSWORD` dans `.env`
2. Définir `UPLOAD_API_KEY` pour sécuriser l'upload agent
3. Utiliser PostgreSQL via `DATABASE_URL`
4. Ne pas exposer le dashboard sans HTTPS (Nginx + SSL)

## Statut v9.2

| Module | État |
|--------|------|
| Agent Windows / SMART / Rapport | ✅ Production atelier |
| Import ZIP / Historique machines | ✅ Fonctionnel |
| Dashboard / Auth | ✅ Fonctionnel |
| Factures / Tickets | ⚠️ Base présente, PDF pro à finaliser |
| Devis | ❌ À développer (v10) |
| USB / WinPE | ⚠️ Scripts présents, intégration à renforcer |

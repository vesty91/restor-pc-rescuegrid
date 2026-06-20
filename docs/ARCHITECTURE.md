# Architecture Restor-PC RescueGrid

## Vue d'ensemble

```txt
Clé USB technicien / WinPE
        -> Agent diagnostic local (PowerShell)
        -> Dossier intervention + BlackBox + SHA256
        -> Archive ZIP
        -> Upload dashboard (session ou clé API)
        -> Historique client / rapports / sauvegardes
```

## Composants

### Agent Windows portable

Rôle : exécuter le diagnostic sans installation lourde.

Fonctions :

- inventaire machine (CPU, RAM, BIOS, GPU, disques, drivers) ;
- disques, volumes, partitions, BitLocker ;
- SMART via PowerShell, `smartctl`, CrystalDiskInfo ;
- journaux système récents et analyse Windows ;
- sauvegarde profil via `robocopy` ;
- classification disque sain / suspect / critique ;
- rapport HTML, BlackBox JSON, manifeste `evidence_manifest.json` ;
- hashes SHA256, archive ZIP.

### Dashboard NAS

Rôle : centraliser clients, interventions et archives.

Stack :

- **FastAPI** (API + routes HTML) ;
- **SQLAlchemy 2.0** (SQLite local, PostgreSQL en production via `DATABASE_URL`) ;
- **Jinja2** (templates) ;
- **JWT** en cookie HTTP-only (auth admin / technicien) ;
- stockage fichiers local (`storage/`) ou montage NAS.

Sécurité :

- routes CRUD protégées par session ;
- suppressions réservées au rôle `admin` ;
- upload ZIP : session connectée ou `UPLOAD_API_KEY` ;
- fichiers stockés servis via `/storage/...` (auth requise).

### WinPE / USB / PXE

- `Invoke-RescueGrid.ps1` : agent principal ;
- `Build-RescueGridUSB.ps1` / `Create-RescueGridUSB.ps1` : clé USB bootable ;
- `Setup-PXERescueServer.ps1` : boot réseau ;
- mode hors ligne via `-OfflineWindowsPath`.

### Déploiement Synology

`docker-compose.synology.yml` :

- PostgreSQL 16
- Backend FastAPI
- Nginx (reverse proxy, `nginx/nginx.conf`)
- MinIO (stockage S3 — intégration applicative à venir)
- pgAdmin (optionnel)

## Règle de sécurité données

```txt
Disque sain    -> copie fichiers
Disque suspect -> image disque avant réparation
Disque mourant -> ddrescue avant toute action destructive
```

L'agent ne lance pas `chkdsk /f`, formatage, suppression ou réparation destructive automatiquement.

## Modèle de données

- `Client` — fiches clients
- `Machine` — historique par serial BIOS
- `Intervention` — rapport importé, scores, risques, statuts atelier
- `Part` — inventaire pièces détachées
- `Invoice` — facturation (HT, TVA, TTC)
- `Ticket` — suivi SAV lié aux interventions
- `User` — comptes dashboard (admin, technicien)

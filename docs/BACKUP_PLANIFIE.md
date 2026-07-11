# Sauvegarde automatique planifiée

Ce document couvre les deux volets de la sauvegarde planifiée introduits en v12.3 :

1. **Côté poste client** — tâche planifiée Windows relançant l'agent RescueGrid
   (sauvegarde + upload) sans intervention du technicien.
2. **Côté serveur dashboard** — sauvegarde périodique automatique de la base
   de données (SQLite ou PostgreSQL) avec rotation.

## 1. Sauvegarde planifiée sur un poste client

### Prérequis — consentement

Avant d'installer une tâche planifiée qui va collecter/sauvegarder les données
d'un client de manière récurrente et silencieuse, le consentement du client
doit avoir été obtenu **manuellement**, comme pour toute intervention (voir le
consentement interactif d'`Invoke-RescueGrid.ps1`). `-SkipConsent` ne
supprime que l'invite interactive lors des exécutions automatiques
ultérieures — il ne remplace jamais cet accord initial. Conservez une trace
écrite de cet accord (devis/mandat signé, mention dans la fiche client).

### Installation

Depuis `agent\windows\`, en invite PowerShell **administrateur** (requis pour
créer une tâche planifiée exécutée en tant que SYSTEM) :

```powershell
powershell -ExecutionPolicy Bypass -File Register-RescueGridScheduledTask.ps1 `
    -ClientName "Dupont Jean" `
    -BackupRoot "E:\RestorPC" `
    -UserProfilePath "C:\Users\Dupont" `
    -DashboardUploadUrl "http://192.168.1.10:8000/upload" `
    -UploadApiKey "votre-cle-upload" `
    -Frequency Daily `
    -TimeOfDay "03:30"
```

Ou depuis le menu interactif : `start_agent_windows.bat` → option **8. Planifier
une sauvegarde automatique**.

Paramètres :

| Paramètre | Rôle |
|---|---|
| `-ClientName` | Nom du client (sert aussi à nommer la tâche planifiée) |
| `-BackupRoot` | Dossier local où stocker l'intervention avant upload |
| `-UserProfilePath` | Profil utilisateur à sauvegarder (optionnel) |
| `-BackupEssentialFoldersOnly` | Limite la sauvegarde à Bureau/Documents/... |
| `-DashboardUploadUrl` | URL `/upload` du dashboard (upload automatique) |
| `-UploadApiKey` | Clé d'API si le dashboard exige `UPLOAD_API_KEY` |
| `-Frequency` | `Daily` ou `Weekly` |
| `-TimeOfDay` | Heure locale au format `HH:mm` |

La tâche s'exécute en tant que **SYSTEM** (pas besoin de session utilisateur
ouverte) et relance `Invoke-RescueGrid.ps1` avec `-SilentMode -SkipConsent
-CreateZip`.

### Suppression

```powershell
powershell -ExecutionPolicy Bypass -File Register-RescueGridScheduledTask.ps1 -Unregister -ClientName "Dupont Jean"
```

Ou menu → option **9. Supprimer une sauvegarde planifiée**.

### Configuration via clé USB (`rescuegrid.env`)

Si la clé USB a été créée avec `Create-RescueGridUSB.ps1 -DashboardUrl ...`,
le fichier `config\rescuegrid.env` qui y est écrit est maintenant **lu
automatiquement** par `Invoke-RescueGrid.ps1` et `Start-RescueGrid.ps1` :
`RESCUEGRID_DASHBOARD_URL`, `RESCUEGRID_BACKUP_ROOT`,
`RESCUEGRID_UPLOAD_API_KEY` servent de valeurs par défaut lorsque les
paramètres correspondants ne sont pas fournis explicitement. Cela évite de
ressaisir l'URL du dashboard à chaque lancement depuis la clé.

## 2. Sauvegarde planifiée côté serveur (base de données)

Activée par défaut (`BACKUP_SCHEDULE_ENABLED=true`). Le serveur FastAPI lance
une tâche de fond au démarrage qui, chaque jour à `BACKUP_SCHEDULE_HOUR`
(3h UTC par défaut), effectue automatiquement :

- **SQLite** (dev / petite installation) : copie du fichier `.db` vers
  `STORAGE_PATH/backups/rescuegrid_<horodatage>.db`.
- **PostgreSQL** (Synology / production) : `pg_dump` vers
  `STORAGE_PATH/backups/rescuegrid_<horodatage>.sql` (nécessite le paquet
  `postgresql-client`, déjà installé dans l'image Docker `backend`).

Rotation : seules les `BACKUP_RETENTION_COUNT` sauvegardes les plus récentes
sont conservées (14 par défaut) ; les plus anciennes sont supprimées
automatiquement.

Variables d'environnement (`.env`) :

```bash
BACKUP_SCHEDULE_ENABLED=true    # false pour désactiver le scheduler interne
BACKUP_SCHEDULE_HOUR=3          # heure UTC de déclenchement quotidien (0-23)
BACKUP_RETENTION_COUNT=14       # nombre de sauvegardes conservées
```

### Interface

Page **Outils technicien** (`/tools`) → carte "Sauvegarde base de données" →
lien **Historique des sauvegardes planifiées** (`/backup/history`, accès
administrateur) :

- Liste des sauvegardes existantes (nom, date, taille) avec téléchargement.
- Bouton **Sauvegarder maintenant** pour déclencher une sauvegarde immédiate
  hors planning (utile avant une opération risquée : migration, mise à jour).
- Rappel de la politique de rétention et du moteur utilisé (SQLite/PostgreSQL).

Le téléchargement brut existant (`/backup/database`, SQLite uniquement) reste
disponible séparément pour un export ponctuel simple.

### Limites connues

- La sauvegarde planifiée serveur ne couvre que la base de données, pas les
  fichiers dans `STORAGE_PATH/uploads` et `STORAGE_PATH/reports` (archives ZIP
  et rapports clients). Pour un NAS Synology, ces dossiers sont déjà sur un
  volume monté qui bénéficie normalement du plan de sauvegarde Synology
  (Hyper Backup) — voir [SYNOLOGY_DEPLOY.md](SYNOLOGY_DEPLOY.md).
- `pg_dump` nécessite que le conteneur `backend` puisse joindre le service
  `postgres` réseau Docker (`DATABASE_URL`) — vérifier `docker compose logs
  backend` en cas d'échec récurrent (visible dans les logs serveur et dans le
  message d'erreur affiché sur `/backup/history` après un déclenchement manuel).

# Déploiement Synology / mode multi-poste

Ce guide décrit le déploiement de production de Restor-PC RescueGrid sur un
NAS Synology (via Container Manager / Docker), pour un usage par plusieurs
postes techniciens simultanément (mode multi-poste).

## Vue d'ensemble de la stack

`docker-compose.synology.yml` définit :

| Service | Rôle | Port |
|---|---|---|
| `postgres` | Base de données (remplace SQLite en production) | interne |
| `minio` | Stockage S3 compatible (déployé, **non utilisé** par le backend actuellement — voir note ci-dessous) | 9000 / 9001 |
| `backend` | Application FastAPI (dashboard) | interne (derrière nginx) |
| `nginx` | Reverse proxy HTTP/HTTPS | 80 / 443 |
| `pgadmin` | Administration PostgreSQL (optionnel) | 5050 |

> **Note MinIO** : le service MinIO est provisionné dans la stack mais le
> backend ne l'utilise pas — le stockage des archives ZIP/rapports
> (`STORAGE_PATH`) reste un système de fichiers classique. Pour un NAS, ce
> dossier est déjà partagé/persistant via le montage Synology ci-dessous ;
> l'intégration applicative S3 n'est pas nécessaire pour le mode multi-poste
> et n'a pas été ajoutée dans ce lot (voir roadmap si un besoin S3 explicite
> apparaît plus tard, par exemple réplication multi-site).

## Étapes de déploiement

### 1. Préparer les dossiers partagés Synology

Sur le NAS, créez (via DSM → Panneau de configuration → Dossier partagé, ou
en SSH) un dossier partagé dédié, par exemple `/volume1/docker/rescuegrid/`.
Le stockage des fichiers uploadés (archives ZIP, rapports HTML, sauvegardes
planifiées) doit vivre sur ce volume Synology pour bénéficier de :

- la persistance au-delà du cycle de vie des conteneurs ;
- la protection par les fonctionnalités NAS (RAID, snapshots BTRFS,
  Hyper Backup) ;
- l'accès partagé si plusieurs postes déposent des interventions.

Clonez/copiez le projet dans ce dossier partagé (ou dans un sous-dossier),
puis assurez-vous que `./volumes/` (référencé par `docker-compose.synology.yml`)
pointe vers ce même volume — soit en plaçant le projet directement dedans,
soit en adaptant les chemins de `docker-compose.synology.yml` :

```yaml
backend:
  volumes:
    - /volume1/docker/rescuegrid/storage:/app/storage
    - /volume1/docker/rescuegrid/reports:/app/reports
```

### 2. Configurer `.env`

```powershell
Copy-Item .env.example .env
```

**Ces variables sont obligatoires** : `docker-compose.synology.yml` refuse de
démarrer si elles ne sont pas définies dans `.env` (aucune valeur par défaut
n'est fournie, volontairement, pour éviter tout déploiement avec un mot de
passe connu/documenté) :

- `SECRET_KEY` — clé JWT staff. Générer avec `openssl rand -hex 32` (ou laisser
  vide en développement local hors Docker : une clé est alors auto-générée et
  persistée dans `backend/.secret_key`, voir `app/auth.py`).
- `ADMIN_PASSWORD` — mot de passe admin initial (10 caractères min., lettres +
  chiffres). Si omis en développement local (hors ce compose), un mot de passe
  aléatoire est généré et affiché une seule fois dans les logs au démarrage.
- `POSTGRES_PASSWORD`
- `MINIO_ROOT_PASSWORD` (même si MinIO n'est pas utilisé applicativement,
  la console reste exposée — désormais liée à `127.0.0.1:9001` uniquement,
  accès via tunnel SSH/VPN)
- `PGADMIN_PASSWORD` (console liée à `127.0.0.1:5050`, idem)

Configurez aussi `DATABASE_URL` pour pointer vers le service `postgres` du
compose (déjà fait par défaut dans `docker-compose.synology.yml` via les
variables `POSTGRES_*`). Une fois nginx configuré en HTTPS à l'étape 5,
ajoutez `COOKIE_SECURE=true` dans `.env` (à `false` par défaut, pour ne pas
casser la connexion tant que HTTPS n'est pas actif — un cookie `Secure` n'est
jamais renvoyé par le navigateur en HTTP).

Le conteneur backend s'exécute en utilisateur non-root (UID/GID 1000, voir
`backend/Dockerfile`). Si les dossiers `./volumes/storage` et
`./volumes/reports` appartiennent à un autre utilisateur sur le NAS, ajustez
leurs permissions, par ex. : `chown -R 1000:1000 ./volumes/storage
./volumes/reports` (ou `chmod -R o+rwX` si `chown` n'est pas disponible via
l'interface DSM).

### 3. Démarrer la stack

Depuis Container Manager (interface DSM) ou en SSH sur le NAS :

```bash
docker compose -f docker-compose.synology.yml up -d
```

Vérifiez la santé des services :

```bash
docker compose -f docker-compose.synology.yml ps
curl http://localhost:8000/health   # depuis le NAS, ou via nginx sur le port 80/443
```

### 4. Appliquer les migrations (étape obligatoire, non automatique sur PostgreSQL)

Contrairement à SQLite en développement (où `init_db()` crée les tables et
stampe Alembic automatiquement au premier démarrage), **PostgreSQL nécessite
une application manuelle des migrations** avant le premier lancement
utilisable :

```bash
docker compose -f docker-compose.synology.yml exec backend alembic upgrade head
```

À refaire après chaque mise à jour du projet qui ajoute une migration
(`alembic/versions/*.py`).

### 5. Configurer nginx (domaine + HTTPS)

`nginx/nginx.conf` définit le reverse proxy. Pour un accès depuis Internet
(ou même en LAN avec HTTPS) :

- Renseignez votre nom de domaine ou l'IP du NAS dans la configuration serveur.
- Placez un certificat dans `./nginx/ssl/` (le montage est déjà prévu dans le
  compose), ou utilisez le certificat géré par DSM (Let's Encrypt via
  Panneau de configuration → Sécurité → Certificat) et pointez nginx dessus.
- `client_max_body_size 2g` est déjà configuré pour accepter les grosses
  archives ZIP d'intervention.

### 6. Configurer chaque poste technicien (mode multi-poste)

Chaque poste technicien doit pointer son agent vers l'URL réseau du NAS
plutôt que `localhost` :

- Lors de la création de la clé USB : `-DashboardUrl "http://<ip-nas>:8000"`
  (ou l'URL nginx/domaine).
- Lors d'un envoi manuel (`start_agent_windows.bat` → option 5, 8) ou d'une
  tâche planifiée (voir [BACKUP_PLANIFIE.md](BACKUP_PLANIFIE.md)) : même URL,
  suffixée de `/upload`.
- Configurez `UPLOAD_API_KEY` côté serveur (`.env`) et passez la même clé à
  chaque agent (`-UploadApiKey`) pour éviter l'upload anonyme sur un réseau
  partagé par plusieurs postes.

### 7. Fiabilité multi-poste — ce qui a été corrigé/vérifié dans ce lot

- **Bug corrigé** : l'import ZIP (`/upload`) ne lisait qu'un `manifest.json`
  jamais produit par l'agent, laissant `bios_serial`/`health_score` vides et
  cassant la déduplication des machines entre postes. Corrigé pour lire
  `inventory.json` (schéma réel produit par l'agent).
- **Ajustement** : la correspondance du nom client à l'upload est désormais
  insensible à la casse/espaces, pour éviter que deux techniciens sur deux
  postes créent deux fiches client distinctes pour la même personne.
- Chaque upload est horodaté (`YYYYMMDD_HHMMSS_client_fichier.zip`), donc les
  uploads simultanés depuis plusieurs postes ne se percutent pas au niveau
  fichier.

### 8. Sauvegarde de la base sur NAS

Le scheduler serveur (voir [BACKUP_PLANIFIE.md](BACKUP_PLANIFIE.md)) utilise
`pg_dump` automatiquement lorsque `DATABASE_URL` est PostgreSQL — aucune
configuration additionnelle requise sur Synology au-delà des variables
`BACKUP_SCHEDULE_*` dans `.env`. Les sauvegardes sont écrites dans
`STORAGE_PATH/backups`, donc sur le volume Synology monté — pensez à inclure
ce dossier dans votre plan Hyper Backup NAS pour une copie hors du NAS lui-même.

## Hors périmètre (pour l'instant)

- Intégration applicative MinIO/S3 (stockage objet) dans le backend.
- Modèle de données "poste de travail" dédié (chaque upload reste identifié
  par client/machine, pas par poste technicien).

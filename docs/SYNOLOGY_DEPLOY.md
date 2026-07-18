# Déploiement Synology / mode multi-poste

Ce guide décrit le déploiement de production de Restor-PC RescueGrid sur un
NAS Synology (via Container Manager / Docker), pour un usage par plusieurs
postes techniciens simultanément (mode multi-poste).

## Vue d'ensemble de la stack

`docker-compose.synology.yml` définit :

| Service | Rôle | Port |
|---|---|---|
| `postgres` | Base de données (remplace SQLite en production) | interne |
| `minio` | Stockage S3 compatible (déployé, **non utilisé** par le backend actuellement — voir note ci-dessous) | 19000 / 9001 (hôte, si 9000 est déjà pris) |
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
curl http://localhost:8080/health   # depuis le NAS, ou via nginx sur le port 80/443
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

### 5. Configurer le domaine + HTTPS — `espace-client.restor-pc.fr`

Le domaine `restor-pc.fr` (et `www.`) héberge déjà le site vitrine de
l'atelier ailleurs (WordPress) — **ne pas le repointer vers le NAS**. Le
dashboard RescueGrid est exposé sur le sous-domaine dédié
`espace-client.restor-pc.fr`, à ajouter en DNS chez le registrar/hébergeur
du domaine (même cible que `nas.restor-pc.fr`, déjà fonctionnel) :

```
espace-client.restor-pc.fr.   CNAME   nas.restor-pc.fr.
```
*(ou un enregistrement A vers la même IP publique si `nas.restor-pc.fr` est
un A plutôt qu'un DDNS).*

Deux façons d'exposer le service en HTTPS — **choisir l'une des deux**, pas
les deux à la fois (conflit de port 80/443) :

**Option A — Reverse Proxy DSM (recommandée sur Synology)**

Certificat Let's Encrypt géré et renouvelé automatiquement par DSM, sans
conteneur nginx supplémentaire à maintenir.

1. `docker compose -f docker-compose.synology.yml up -d` (le service
   `backend` publie déjà `127.0.0.1:8080` sur l'hôte — voir le compose ;
   port 8080 et non 8000 si un autre outil comme Portainer occupe déjà
   ce dernier sur le NAS).
2. DSM → Panneau de configuration → Sécurité → Certificat → **Ajouter** →
   Let's Encrypt → domaine `espace-client.restor-pc.fr`.
3. DSM → Panneau de configuration → Portail de connexion → Avancé →
   **Reverse Proxy** → Créer :
   - Source : HTTPS, `espace-client.restor-pc.fr`, port 443.
   - Destination : HTTP, `localhost`, port 8080.
   - Onglet "En-tête personnalisé" : ajouter `X-Forwarded-Proto = https`
     (nécessaire pour que l'application sache qu'elle est servie en HTTPS).
4. Associer le certificat Let's Encrypt créé à l'étape 2 à ce Reverse Proxy
   (DSM → Certificat → ... → Configurer les services, ou directement dans
   les paramètres du Reverse Proxy selon la version de DSM).
5. Ne pas démarrer le service `nginx` du compose dans ce cas (`docker compose
   -f docker-compose.synology.yml up -d --scale nginx=0`, ou retirer le
   service `nginx` du fichier si l'option A est définitive).

**Option B — Conteneur nginx du compose (si ports 80/443 libres sur le NAS)**

1. Obtenir un certificat pour `espace-client.restor-pc.fr` (Let's Encrypt via
   DSM comme ci-dessus, puis exporter `cert.pem`/`key.pem` dans `./nginx/ssl/`,
   ou `certbot` en mode standalone/DNS).
2. Dans `nginx/nginx.conf` : décommenter le bloc HTTPS (`listen 443 ssl`) et
   la ligne `return 301 https://$host$request_uri;` du bloc port 80.
3. `docker compose -f docker-compose.synology.yml restart nginx`.

Dans les deux cas, une fois le HTTPS actif, définir dans `.env` :

```
COOKIE_SECURE=true
OAUTH_REDIRECT_BASE_URL=https://espace-client.restor-pc.fr
```

`client_max_body_size 2g` est déjà configuré (nginx du compose) pour
accepter les grosses archives ZIP d'intervention ; en option A, la limite
équivalente côté DSM Reverse Proxy est généralement suffisante par défaut
mais peut être ajustée si des imports volumineux échouent (413).

### 6. Configurer chaque poste technicien (mode multi-poste)

Chaque poste technicien doit pointer son agent vers l'URL réseau du NAS
plutôt que `localhost` :

- Lors de la création de la clé USB : `-DashboardUrl "https://espace-client.restor-pc.fr"`
  une fois HTTPS actif (étape 5). Le port backend (8080 par défaut, voir le
  compose) n'est publié que sur `127.0.0.1` du NAS ; pour un accès LAN direct
  sans HTTPS, changez temporairement ce binding en `0.0.0.0:8080:8000` dans
  `docker-compose.synology.yml` (déconseillé hors réseau de confiance).
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

### 9. Paiement en ligne — configurer le webhook Stripe

Le lien de paiement sur les factures (`app/stripe_payments.py`) est optionnel :
sans `STRIPE_SECRET_KEY`, rien ne change. Pour l'activer en production :

1. Récupérer la **clé secrète** (mode live, une fois les tests validés en mode
   test) sur https://dashboard.stripe.com/apikeys et la renseigner dans `.env` :

   ```
   STRIPE_SECRET_KEY="sk_live_..."
   ```

2. Créer le webhook sur https://dashboard.stripe.com/webhooks :
   - URL du point de terminaison : `https://espace-client.restor-pc.fr/stripe/webhook`
   - Événement à écouter : `checkout.session.completed`
   - Copier la **clé de signature** (`whsec_...`) affichée après création et la
     renseigner dans `.env` :

     ```
     STRIPE_WEBHOOK_SECRET="whsec_..."
     ```

3. `docker compose -f docker-compose.synology.yml up -d backend` (ou `restart`)
   pour recharger les nouvelles variables d'environnement.
4. Vérifier depuis le dashboard Stripe (bouton "Envoyer un événement de test")
   que le webhook répond `200`. Une facture réellement payée via le lien passe
   alors automatiquement au statut « Payée » sans action du technicien.

Sans HTTPS actif (étape 5 ci-dessus), Stripe ne peut pas appeler le webhook —
le paiement fonctionne quand même côté client (Checkout Stripe est toujours en
HTTPS), mais la confirmation automatique du statut ne pourra pas remonter tant
que `espace-client.restor-pc.fr` n'est pas servi en HTTPS.

### 10. Relances automatiques — activer le cron interne (optionnel)

Par défaut, les relances devis/factures en retard restent 100% manuelles
(bouton « Relancer » sur `/relances`). Pour les automatiser :

```
REMINDER_SCHEDULE_ENABLED=true
REMINDER_SCHEDULE_HOUR=8        # heure UTC de vérification quotidienne
REMINDER_COOLDOWN_DAYS=7        # délai minimum entre deux relances du même document
```

Puis redémarrer le backend. L'état courant (activé/désactivé) est affiché en
bannière sur `/relances`.

### 11. Déploiement automatique (CD) — sans manipulation SSH manuelle

Un script (`scripts/nas_auto_deploy.sh`) automatise la mise à jour : détection
d'un nouveau commit sur `origin/main`, `git pull`, reconstruction de l'image
`backend` (taguée par hash Git pour rollback manuel), **garde de tests**
(la suite de tests tourne dans un conteneur jetable de la nouvelle image,
base SQLite isolée — un test qui casse annule tout le déploiement avant même
de toucher la base de production), migration Alembic (avant la bascule du
conteneur, pas après), bascule du conteneur, puis vérification `/health` —
avec rollback automatique vers l'image précédente si le healthcheck échoue,
et notification push (ntfy) en cas de succès **ou** d'échec à chaque étape.

**Pourquoi un script planifié sur le NAS plutôt qu'un webhook GitHub → NAS ?**
Le NAS n'expose sur internet que le port 443 (voir étape 5) ; un webhook de
déploiement obligerait à ouvrir un nouveau port, ou à donner au conteneur
backend (déjà public) un accès au socket Docker de l'hôte — un niveau de
confiance équivalent à root accordé à un service exposé publiquement. Un
script planifié tournant directement sur l'hôte atteint le même objectif
(zéro manipulation SSH après un `git push`) sans nouvelle surface d'attaque ;
seul coût : jusqu'à ~15 minutes de latence entre le push et le déploiement
effectif (configurable via la fréquence de la tâche planifiée).

**Sûr par construction** : le marqueur `.last_deployed_commit` (à la racine du
projet, non versionné) n'avance qu'après un déploiement **intégralement**
réussi. Si le build, le redémarrage, la migration ou le healthcheck échoue,
l'ancien conteneur continue de tourner sans interruption, une alerte ntfy est
envoyée, et le script retentera le même commit à la prochaine exécution.

**Mise en place (une seule fois) :**

1. Rendre les scripts exécutables sur le NAS (droits perdus lors du transfert
   Windows → Linux) :

   ```bash
   chmod +x /volume1/docker/rescuegrid/scripts/nas_auto_deploy.sh
   chmod +x /volume1/docker/rescuegrid/scripts/notify_deploy.sh
   ```

2. Initialiser le marqueur avec le commit actuellement déployé, pour éviter
   un premier déclenchement inutile au prochain run :

   ```bash
   cd /volume1/docker/rescuegrid
   git rev-parse HEAD > .last_deployed_commit
   ```

3. DSM → Panneau de configuration → Planificateur de tâches → Créer →
   **Tâche déclenchée** → Script défini par l'utilisateur :
   - Compte utilisateur : `root` (nécessaire pour appeler `docker`).
   - Calendrier : répéter toutes les **15 minutes**, tous les jours.
   - Tâche → Exécuter la commande :

     ```
     bash /volume1/docker/rescuegrid/scripts/nas_auto_deploy.sh
     ```

4. Vérifier après le premier déclenchement : le fichier
   `/volume1/docker/rescuegrid/logs/auto_deploy.log` doit contenir
   `Déjà à jour (...)`. Pour tester réellement le pipeline, faites un petit
   commit sur `main` depuis votre poste, poussez-le, puis attendez le prochain
   run (ou déclenchez la tâche manuellement depuis DSM avec le bouton
   « Exécuter ») et surveillez le log + la notification ntfy.

À partir de là, un simple `git push` vers `main` suffit : le NAS se met à
jour de lui-même dans les ~15 minutes qui suivent, sans connexion SSH.

## Hors périmètre (pour l'instant)

- Intégration applicative MinIO/S3 (stockage objet) dans le backend.
- Modèle de données "poste de travail" dédié (chaque upload reste identifié
  par client/machine, pas par poste technicien).

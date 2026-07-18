# Changelog

## v12.5.1 — Durcissement technique (priorités revue qualité)

- **IP réelle derrière reverse proxy** : `get_client_ip()` (deps.py) lit
  `X-Forwarded-For` uniquement depuis un proxy de confiance.
- **Python 3.12 uniquement** dans `install_dependencies.ps1` (recréation du
  `.venv` si version incompatible).
- **`start_dashboard.bat`** : plus de `pip install` à chaque démarrage ;
  exécute `alembic upgrade head` puis uvicorn sur `127.0.0.1`.
- **Chemins ZIP / storage** : `Path.is_relative_to()` à la place de
  `startswith`.
- **Upload ZIP** : écriture disque par blocs de 8 Mo (plus de lecture 2 Go en RAM).
- **`docker-compose.dev.yml`** : secrets via `.env`, port lié à `127.0.0.1`.
- **SQLite** : `PRAGMA foreign_keys=ON` ; sauvegarde via `Connection.backup()`.
- **Alembic** : stamp `head` uniquement sur BDD vraiment vierge ; procédure
  explicite pour bases existantes sans `alembic_version`.
- **Déploiement NAS** : tests + migration **avant** bascule conteneur,
  images taguées par hash Git, rollback auto si `/health` échoue.
- **Montants** : `Numeric(12,2)` / `Decimal` (migration `0009_money_numeric`)
  + `to_money()` / `allocate_document_number()` (retry sur collision UNIQUE).
- **FK ON DELETE** explicites (migration `0008_fk_ondelete`).
- **Version** unique via fichier `VERSION` (`app/version.py`, `/health`).
- **Profils Docker** : `s3` (MinIO), `nginx`, `admin` (pgAdmin) — optionnels.
- **Script** `scripts/make_release_zip.py` pour un ZIP de release propre.
- **CSRF** : jetons double-submit (`csrf_token` cookie + champ/header) en
  complément Origin/Referer ; formulaires login/2FA/espace client couverts.
- **Rate-limit persistant** (migration `0010_rate_limit`) + verrous scheduler.
- **Dashboard** : agrégats SQL (COUNT/SUM) au lieu de tout charger en mémoire.
- **Découpage** : `routes_v10` → `routes/quotes|relances|settings_admin|
  intervention_extras` + `services/mail|reminders|billing_defaults`.
- **Qualité** : `pyproject.toml` (ruff/mypy/pytest) ; premiers tests pytest
  unitaires (suite intégration `run_tests.py` conservée, 93/93).

## v12.5.0 — Double authentification admin, fiabilisation des sauvegardes, monitoring et déploiement continu

- **Double authentification (2FA/TOTP) obligatoire pour le compte admin** :
  enrôlement forcé au premier login (QR code + secret, `pyotp`/`qrcode`),
  vérification à chaque connexion suivante, 8 codes de secours à usage unique
  générés à l'activation, réinitialisation possible depuis `/settings`
  (protégée par le mot de passe courant). Non exigée pour les comptes
  technicien. Nouvelle migration Alembic `0007_totp_2fa` (colonnes
  `totp_secret`, `totp_enabled`, `totp_recovery_codes` sur `user`). Limitation
  du nombre de tentatives de code TOTP par IP/compte.
- **Fiabilisation des sauvegardes automatiques** : corrige un échec silencieux
  de `pg_dump` en production (incompatibilité de version entre le client du
  conteneur backend et PostgreSQL 16 du NAS — `backend/Dockerfile` installe
  désormais `postgresql-client-16` depuis le dépôt officiel PGDG). Ajout
  d'alertes push (ntfy, `BACKUP_ALERT_NTFY_URL`) en complément de l'alerte
  email existante en cas d'échec de sauvegarde planifiée. Restauration réelle
  vérifiée sur une base de test à partir d'une sauvegarde de production.
- **Monitoring auto-hébergé (Uptime Kuma)** : nouveau service dans
  `docker-compose.synology.yml` (image épinglée `2.4.0`), pour surveiller la
  disponibilité des conteneurs applicatifs directement depuis le NAS.
- **Déploiement automatique (CD) sans SSH manuel** : `scripts/nas_auto_deploy.sh`,
  déclenché périodiquement par le Planificateur de tâches Synology, détecte les
  nouveaux commits sur `origin/main` et enchaîne `git pull` → reconstruction de
  l'image `backend` → redémarrage → migration Alembic → vérification
  `/health`, avec notification ntfy de succès/échec (`scripts/notify_deploy.sh`).
  Le marqueur `.last_deployed_commit` n'avance qu'après un déploiement
  intégralement réussi : en cas d'échec à n'importe quelle étape, l'ancienne
  version continue de tourner sans interruption. Voir
  [SYNOLOGY_DEPLOY.md](docs/SYNOLOGY_DEPLOY.md) section 11.
- 20 nouveaux tests de régression (`backend/tests/run_tests.py`) couvrant
  l'ensemble du flux 2FA (enrôlement forcé, code invalide, codes de secours,
  usage unique, non-exigence pour les techniciens). 93 tests au total, tous
  au vert.

## v12.4.0 — Paiement en ligne Stripe + relances automatiques

- **Paiement en ligne (Stripe Checkout)** : chaque facture émise peut générer
  un lien de paiement par carte bancaire (`app/stripe_payments.py`), affiché
  dans le PDF, l'email d'envoi/relance et sur `/invoices` (bouton « Lien de
  paiement » + bandeau copier-coller). La confirmation de paiement est
  automatique via webhook Stripe (`POST /stripe/webhook`, événement
  `checkout.session.completed`) : la facture passe alors à `paid` sans action
  du technicien. Fonctionnalité entièrement optionnelle : sans
  `STRIPE_SECRET_KEY` dans `.env`, le comportement est strictement identique à
  avant (pas de lien, pas d'appel réseau). Nouvelles colonnes sur `invoice`
  (migration Alembic `0006_stripe_invoice_fields`) : `stripe_checkout_session_id`,
  `stripe_payment_link_url`, `stripe_link_expires_at`.
- **Relances automatiques (cron interne)** : les devis/factures en retard
  peuvent désormais être relancés automatiquement (`app/reminders_scheduler.py`,
  calqué sur le scheduler de sauvegarde), avec un délai minimum de 7 jours
  entre deux relances du même document. **Désactivé par défaut**
  (`REMINDER_SCHEDULE_ENABLED=false`) : les relances restent 100% manuelles
  (bouton sur `/relances`) tant que la variable n'est pas activée. Une
  bannière sur `/relances` indique l'état courant (activé/désactivé).
- Extraction de `send_quote_reminder`/`send_invoice_reminder` en fonctions
  partagées (`app/routes_v10.py`), réutilisées par les routes HTTP existantes
  et par le nouveau scheduler.
- 12 nouveaux tests de régression (`backend/tests/run_tests.py`) : PDF sans clé
  Stripe, webhook à signature invalide, facture payée n'obtenant jamais de
  lien, scheduler désactivé par défaut, cooldown de relance (skip/allow/aucun
  historique).

## v12.3.6 — PDF devis/factures tenant sur une seule page

- Resserrement général des marges/espacements du gabarit PDF (`document_html`
  dans `backend/app/helpers.py`) : marges de page, en-tête société, encadré
  info client/intervention, liste technique, tableau d'articles, tableau des
  totaux, encadré de règlement, bloc signatures et pied de page.
- Réduction ciblée des tailles de police et hauteurs de ligne (sans perte de
  lisibilité) et de la hauteur des cadres de signature (16 mm → 12 mm).
- Corrige le débordement observé où le pied de page (mentions TVA/CGI) se
  retrouvait seul sur une deuxième page alors que le reste du document tenait
  sur la première.

## v12.3.5 — Nouveau design sobre des devis/factures

- Remplacement du gabarit "premium" (panneau sombre, dégradés, formes
  diagonales) par une mise en page classique et épurée, plus proche d'un
  document professionnel standard : fond blanc, fine ligne d'accent
  turquoise, encadrés gris-bleu clair pour les blocs d'informations, en-tête
  de tableau sombre, ligne de total mise en évidence.
- Mise en page basée sur des `<table>` HTML plutôt que sur CSS grid/flexbox,
  ce qui la rend également robuste sur les moteurs de secours (wkhtmltopdf,
  xhtml2pdf) en plus de Chromium.

## v12.3.4 — Moteur PDF Chromium (design pro devis/factures)

- Le gabarit PDF (`document_html` dans `backend/app/helpers.py`) utilise CSS
  grid, flexbox et dégradés. Or `wkhtmltopdf` embarque un moteur WebKit gelé
  depuis 2012, **sans aucun support de CSS grid** : les colonnes (panneau de
  marque, deux blocs adresse/intervention, lignes icône+texte) s'effondraient
  en un rendu tronqué/illisible malgré le correctif v12.3.3.
- **Chromium headless** est désormais le moteur PRINCIPAL de génération PDF
  (`render_document_pdf`) : rendu fidèle à 100 % au design (dégradés, grid,
  couleurs, icônes). `wkhtmltopdf` reste installé en repli, `xhtml2pdf` en
  tout dernier recours.
- `backend/Dockerfile` installe le paquet `chromium` ainsi que des polices
  (`fonts-liberation`, `fonts-dejavu-core`, `fonts-noto-core`) pour un rendu
  texte/symboles net (image ≈1.2 Go, build plus long — attendu vu le moteur
  embarqué).
- Remplacement de l'unique emoji couleur (🌐, sans rendu fiable sans police
  d'emoji dédiée) par un symbole simple.

## v12.3.3 — Correctif génération PDF (devis/factures)

- **Bug bloquant en production** : les PDF de devis/factures échouaient
  silencieusement (`xhtml2pdf` ne supporte pas les variables CSS `var(--rp-*)`
  utilisées dans le template HTML), et l'application repartait sur le
  dernier recours : l'envoi du document en pièce jointe HTML brute au lieu
  d'un PDF. Toutes les couleurs `var(--rp-*)` du template de génération PDF
  (`document_html` dans `backend/app/helpers.py`, partagé par devis et
  factures) ont été remplacées par leurs valeurs hexadécimales littérales.
  Vérifié en production : le document généré est désormais un vrai
  `%PDF-1.4` valide.

## v12.3.2 — Revue de sécurité complète

Correctifs suite à un audit manuel de l'ensemble du projet (auth, autorisation,
injection, secrets, rate limiting, dépendances, scripts PowerShell, Docker,
en-têtes HTTP) :

- **Critique** : plus de `SECRET_KEY`/`ADMIN_PASSWORD` par défaut connus —
  clé JWT auto-générée et persistée (`backend/.secret_key`) si absente de
  l'environnement, mot de passe admin initial aléatoire affiché une seule fois
  au premier démarrage si `ADMIN_PASSWORD` n'est pas défini. `docker-compose.synology.yml`
  refuse désormais de démarrer sans `POSTGRES_PASSWORD`/`MINIO_ROOT_PASSWORD`/
  `SECRET_KEY`/`ADMIN_PASSWORD`/`PGADMIN_PASSWORD` explicites (plus de mot de
  passe par défaut `rescuegrid2026`). `GET /backup/database` réservé à
  l'administrateur (était accessible à tout compte staff).
- **Élevé** : cookies de session `Secure` configurables (`COOKIE_SECURE`),
  claim JWT `typ` pour cloisonner strictement sessions staff/client, ports
  MinIO/pgAdmin liés à `127.0.0.1` uniquement, vérification email GitHub OAuth
  durcie (adresses vérifiées uniquement via `/user/emails`), échappement HTML
  de l'étiquette d'intervention et du mode de paiement facture (XSS stockée),
  retrait de `--enable-local-file-access` (wkhtmltopdf), en-têtes de sécurité
  HTTP (CSP, X-Frame-Options, X-Content-Type-Options, HSTS conditionnel),
  conteneur backend exécuté en utilisateur non-root, images MinIO/pgAdmin
  épinglées à une version précise (plus de `:latest`).
- **Moyen** : rejet des liens symboliques dans les archives ZIP importées
  (variante Zip Slip), rate limiting sur `/upload` (clé API), vérification de
  la signature magique ZIP, limites de taille sur logo/photos/signature,
  `POST /invoices` renvoie 400 (au lieu d'un 500) si `intervention_id` est
  invalide, changement de mot de passe ajouté à l'espace client.
- Suite de tests étendue (9 nouveaux tests de régression sécurité, 67/67 au total).

## v12.3.1 — Pipeline ADK WinPE automatisé

- Nouveau script `Build-RescueGridWinPE.ps1` : construit automatiquement
  `boot.wim` (copype + ajout WinPE-WMI/NetFx/Scripting/PowerShell/StorageWMI/
  DismCmdlets + personnalisation `startnet.cmd`) et génère optionnellement une
  ISO bootable (`-BuildIso`), à partir d'un Windows ADK installé localement.
- Raccourci `start_build_winpe.bat` et carte dédiée dans `tools.html`.
- Documentation `TECHNICIAN_MANUAL.md` mise à jour (procédure entièrement
  automatisée, remplace les étapes manuelles précédemment reportées).
- Pipeline validé réellement sur poste de build : ADK + add-on WinPE installés
  via winget, `boot.wim` (~480 Mo) et ISO (~535 Mo) générés avec succès.

## v12.3 — Roadmap v12 priorité 3

- Sauvegarde planifiée serveur (SQLite/pg_dump + rotation, scheduler interne) et agent
  (tâche planifiée Windows, lecture auto de `rescuegrid.env`).
- Correction du bug de métadonnées `/upload` (lecture d'`inventory.json` au lieu d'un
  `manifest.json` inexistant) qui cassait la déduplication machine en mode multi-poste.
- Documentation Synology/multi-poste (`docs/SYNOLOGY_DEPLOY.md`) et manuel technicien
  USB/WinPE (`docs/TECHNICIAN_MANUAL.md`).
- Unification des builders de clé USB (`Create-RescueGridUSB.ps1` canonique,
  `Build-RescueGridUSB.ps1` conservé en alias déprécié).

## v12.2 — Roadmap v12 priorité 2

- Espace client sécurisé (mot de passe, connexion Google et GitHub).
- Planning / prise de rendez-vous.
- Relances devis/factures (suggestion manuelle).
- Export comptable (CSV / Excel).
- Pagination sur les listes principales (clients, machines, interventions, tickets…).
- Renforcement de la politique de mot de passe et verrouillage de compte
  (staff et client, par IP et par identifiant).
- Nettoyage du champ TVA mort dans les formulaires devis/factures.

## v12.1 Hardening

- Remplacement de `datetime.utcnow()` par `datetime.now(timezone.utc)`.
- Suppression du log affichant le mot de passe administrateur par défaut.
- Ajout d'un rate limiting simple sur `/login`.
- Ajout du logging backend pour les erreurs auparavant silencieuses.
- Numérotation devis/factures séquentielle journalière (`DEV-YYYYMMDD-0001`, `INV-YYYYMMDD-0001`).
- Début de consolidation production sans modifier le module de résumé local heuristique.


## v12.0 Stable

- Stabilisation de l'envoi SMTP Infomaniak.
- Suppression définitive du fallback Outlook / mailto.
- Chargement robuste de `.env` racine et `backend/.env`.
- Ajout de `python-dotenv` dans les dépendances.
- PDF devis/factures joints automatiquement aux e-mails.
- Nettoyage documentation pour dépôt GitHub.
- Version prête pour branche de développement v12.

## v11.8 Stable

- Devis/factures premium Restor-PC.
- Signature client et signature Restor-PC.
- TVA auto-entrepreneur.
- Dashboard harmonisé.

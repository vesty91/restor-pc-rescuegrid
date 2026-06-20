# Restor-PC RescueGrid v5.0.0 — Stable Atelier

Cette version vise la stabilité, la sécurité minimale et le déploiement propre en atelier/NAS.

## Changements v5 stabilité

- Projet nettoyé pour distribution : exclusion `.git`, `.venv`, caches, bases locales et archives temporaires.
- Upload ZIP durci :
  - nom de fichier nettoyé ;
  - limite de taille configurable ;
  - protection ZipSlip ;
  - limite du nombre de fichiers extraits ;
  - limite de taille décompressée.
- `STORAGE_PATH` pris en compte par le backend.
- Dockerfile amélioré avec healthcheck et `curl`.
- Support PostgreSQL Docker/Synology via `psycopg[binary]`.
- `.env.example` enrichi avec les limites de sécurité.

## Lancement local

```powershell
powershell -ExecutionPolicy Bypass -File install_dependencies.ps1
.\start_dashboard.bat
```

Dashboard :

```txt
http://localhost:8000
admin / rescuegrid2026
```

Changer immédiatement le mot de passe admin en production via `.env`.

## Lancement Docker

```powershell
docker compose up --build
```

## Lancement Synology/NAS

```bash
cp .env.example .env
# Modifier SECRET_KEY, ADMIN_PASSWORD, POSTGRES_PASSWORD, MINIO_ROOT_PASSWORD
docker compose -f docker-compose.synology.yml up -d
```

## Variables importantes

```env
SECRET_KEY=changer-obligatoirement
ADMIN_PASSWORD=mot-de-passe-fort
STORAGE_PATH=./storage
MAX_UPLOAD_BYTES=2147483648
MAX_ZIP_UNCOMPRESSED_BYTES=4294967296
MAX_ZIP_FILES=10000
```

## Validation avant production

1. Importer un ZIP intervention valide.
2. Importer un ZIP corrompu.
3. Importer un ZIP trop lourd.
4. Tester NAS indisponible.
5. Tester sauvegarde + restauration.
6. Tester compte admin/technicien.
7. Tester Windows 10, Windows 11 et WinPE.
8. Vérifier les manifests SHA256.

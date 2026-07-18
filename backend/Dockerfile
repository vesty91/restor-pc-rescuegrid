FROM python:3.12-slim-bookworm

# Injectée au build (voir docker-compose.synology.yml / nas_auto_deploy.sh) car
# le contexte de build est limité à backend/ : le fichier VERSION à la racine
# du projet n'est pas accessible en COPY depuis ici (voir app/version.py).
ARG APP_VERSION=0.0.0-dev

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    STORAGE_PATH=/app/storage \
    APP_VERSION=${APP_VERSION}

WORKDIR /app

# Chromium headless est le moteur PRINCIPAL de génération PDF (devis/factures,
# voir render_document_pdf dans app/helpers.py) : le gabarit utilise CSS grid,
# flexbox et dégradés, non supportés par le vieux moteur WebKit de wkhtmltopdf
# (gelé depuis 2012). wkhtmltopdf reste installé en repli (compatibilité), et
# xhtml2pdf (pip) en tout dernier recours. Le paquet officiel wkhtmltopdf
# n'étant publié que pour des versions Debian figées, l'image de base est
# épinglée à bookworm pour rester compatible.
# Le dépôt Debian bookworm ne fournit que postgresql-client 15, alors que la
# base de données de production (docker-compose.synology.yml, image
# `postgres:16-alpine`) est en version majeure 16. `pg_dump` refuse par
# sécurité de sauvegarder un serveur plus récent que lui ("aborting because of
# server version mismatch") : toute sauvegarde planifiée échouait silencieusement
# en production. On installe donc `postgresql-client-16` depuis le dépôt
# officiel PGDG plutôt que le paquet générique du dépôt Debian.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        curl gnupg ca-certificates chromium \
        fonts-liberation fonts-dejavu-core fonts-noto-core \
    && install -d /usr/share/postgresql-common/pgdg \
    && curl -fsSL -o /usr/share/postgresql-common/pgdg/apt.postgresql.org.asc \
        https://www.postgresql.org/media/keys/ACCC4CF8.asc \
    && echo "deb [signed-by=/usr/share/postgresql-common/pgdg/apt.postgresql.org.asc] https://apt.postgresql.org/pub/repos/apt bookworm-pgdg main" \
        > /etc/apt/sources.list.d/pgdg.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends postgresql-client-16 \
    && curl -fsSL -o /tmp/wkhtmltox.deb \
        https://github.com/wkhtmltopdf/packaging/releases/download/0.12.6.1-3/wkhtmltox_0.12.6.1-3.bookworm_amd64.deb \
    && apt-get install -y --no-install-recommends /tmp/wkhtmltox.deb \
    && rm -f /tmp/wkhtmltox.deb \
    && fc-cache -f \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY templates ./templates
COPY static ./static
COPY alembic ./alembic
COPY alembic.ini .
# La suite de tests est incluse dans l'image (poids négligeable) pour pouvoir
# la lancer contre l'image nouvellement construite avant bascule en production
# — voir scripts/nas_auto_deploy.sh, étape "garde de tests".
COPY tests ./tests

RUN mkdir -p /app/storage /app/storage/uploads /app/storage/reports

# Exécution en utilisateur non privilégié : un container qui tourne en root
# n'apporte aucun bénéfice ici et aggrave l'impact de toute faille d'exécution
# de code (RCE) dans une dépendance. UID/GID 1000 fixes pour rester cohérents
# avec les permissions des volumes bind-mount (./volumes/... côté hôte) — voir
# docs/SYNOLOGY_DEPLOY.md si un chown du dossier hôte est nécessaire.
RUN groupadd -g 1000 rescuegrid && useradd -u 1000 -g rescuegrid -M -s /usr/sbin/nologin rescuegrid \
    && chown -R rescuegrid:rescuegrid /app
USER rescuegrid

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=10s --retries=3 CMD curl -f http://localhost:8000/health || exit 1
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

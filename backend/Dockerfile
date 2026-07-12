FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    STORAGE_PATH=/app/storage

WORKDIR /app

# Chromium headless est le moteur PRINCIPAL de génération PDF (devis/factures,
# voir render_document_pdf dans app/helpers.py) : le gabarit utilise CSS grid,
# flexbox et dégradés, non supportés par le vieux moteur WebKit de wkhtmltopdf
# (gelé depuis 2012). wkhtmltopdf reste installé en repli (compatibilité), et
# xhtml2pdf (pip) en tout dernier recours. Le paquet officiel wkhtmltopdf
# n'étant publié que pour des versions Debian figées, l'image de base est
# épinglée à bookworm pour rester compatible.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        curl postgresql-client chromium \
        fonts-liberation fonts-dejavu-core fonts-noto-core \
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

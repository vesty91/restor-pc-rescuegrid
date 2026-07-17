#!/bin/sh
# notify_deploy.sh — notification push (ntfy) best-effort pour le déploiement
# automatique (voir nas_auto_deploy.sh). Réutilise le même topic ntfy que les
# alertes de sauvegarde (BACKUP_ALERT_NTFY_URL dans .env) : un seul canal
# d'alerte "exploitation" plutôt que d'exiger un second abonnement ntfy.
#
# Usage : ./notify_deploy.sh "message"
set -eu

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ENV_FILE="$SCRIPT_DIR/../.env"
MESSAGE="${1:-Déploiement RescueGrid}"

if [ ! -f "$ENV_FILE" ]; then
  exit 0
fi

NTFY_URL=$(grep -m1 '^BACKUP_ALERT_NTFY_URL=' "$ENV_FILE" 2>/dev/null | cut -d= -f2-)
if [ -z "$NTFY_URL" ]; then
  exit 0
fi

curl -s -m 10 \
  -H "Title: RescueGrid - deploiement automatique" \
  -H "Tags: rocket,rescuegrid" \
  -d "$MESSAGE" \
  "$NTFY_URL" > /dev/null 2>&1 || true

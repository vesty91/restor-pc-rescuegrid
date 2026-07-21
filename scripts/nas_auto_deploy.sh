#!/bin/bash
# nas_auto_deploy.sh — déploiement continu (CD) pour le NAS Synology
# ---------------------------------------------------------------------------
# À exécuter périodiquement (toutes les ~15 min) via le Planificateur de
# tâches Synology (Panneau de configuration > Planificateur de tâches >
# Créer > Tâche déclenchée > Script défini par l'utilisateur) — voir
# docs/SYNOLOGY_DEPLOY.md section "Déploiement automatique (CD)".
#
# Pourquoi un script planifié plutôt qu'un webhook GitHub -> NAS ?
# Le NAS n'expose que le port 443 (HTTPS) sur internet (voir reverse proxy) ;
# un webhook de déploiement nécessiterait soit d'ouvrir un nouveau port, soit
# de donner au conteneur backend (déjà exposé publiquement) un accès au socket
# Docker de l'hôte pour pouvoir se reconstruire/redémarrer lui-même — un
# niveau de confiance équivalent à root sur le NAS accordé à un service public.
# Un script planifié tournant directement sur l'hôte (donc déjà légitimement
# capable d'exécuter `docker`/`git`) atteint le même objectif (déploiement
# sans intervention manuelle) sans exposer de nouvelle surface d'attaque —
# seul coût : jusqu'à ~15 minutes de latence après un push sur main.
#
# Séquence (chaque étape ne s'exécute que si la précédente a réussi) :
#   1. build de la nouvelle image (le conteneur en prod actuel n'est pas touché)
#   2. tag permanent de cette image par hash Git (rollback possible)
#   3. garde de tests : la suite de tests tourne DANS un conteneur jetable de
#      cette nouvelle image (SQLite isolé, aucun accès à la base de prod) —
#      si un test casse, on s'arrête ici, le conteneur en prod continue de
#      tourner sans interruption avec l'ancienne image
#   4. migration Alembic sur la base de prod, AVANT la bascule du conteneur —
#      avec l'ancien ordre (bascule puis migration), le nouveau code tournait
#      transitoirement contre l'ancien schéma (bug garanti dès qu'une
#      migration ajoute une colonne que le nouveau code lit immédiatement).
#      L'inverse (ancien code contre nouveau schéma, pendant les quelques
#      secondes entre migration et bascule) n'est risqué que si une migration
#      supprime/renomme une colonne encore lue par l'ancien code — situation
#      qui ne s'est jamais produite ici (migrations additives uniquement).
#   5. bascule du conteneur backend sur la nouvelle image
#   6. vérification de santé (/health) ; en cas d'échec, rollback automatique
#      vers la précédente image taguée (la migration, elle, n'est PAS annulée
#      automatiquement — trop risqué sans confirmation humaine)
#
# Sûr par construction : n'avance le marqueur .last_deployed_commit qu'après
# un déploiement intégralement réussi ; en cas d'échec à n'importe quelle
# étape avant la bascule, l'ancien conteneur continue de tourner sans
# interruption et une alerte ntfy est envoyée (voir notify_deploy.sh).
set -uo pipefail

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_DIR" || exit 1

LOG_DIR="$REPO_DIR/logs"
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/auto_deploy.log"
MARKER_FILE="$REPO_DIR/.last_deployed_commit"
COMPOSE_FILE="docker-compose.synology.yml"
DOCKER="/usr/local/bin/docker"
IMAGE_REPO="rescuegrid-backend"
NETWORK="rescuegrid_rescuegrid"
# Nombre d'images taguées par hash à conserver pour un rollback manuel rapide
# (au-delà, les plus anciennes sont supprimées pour ne pas saturer le disque).
KEEP_IMAGES=10

# Ne garde que les 2000 dernières lignes à chaque exécution, pour ne pas
# laisser grossir le log indéfiniment (exécution toutes les ~15 min, sans fin).
if [ -f "$LOG_FILE" ]; then
  tail -n 2000 "$LOG_FILE" > "$LOG_FILE.tmp" && mv "$LOG_FILE.tmp" "$LOG_FILE"
fi

{
  echo "=== $(date -Iseconds) : vérification des mises à jour ==="

  if ! git fetch origin main --quiet; then
    echo "ECHEC : git fetch impossible (réseau ? dépôt distant inaccessible ?)"
    exit 1
  fi

  REMOTE_COMMIT="$(git rev-parse origin/main)"
  DEPLOYED_COMMIT="$(cat "$MARKER_FILE" 2>/dev/null || echo "")"

  if [ "$DEPLOYED_COMMIT" = "$REMOTE_COMMIT" ]; then
    echo "Déjà à jour ($REMOTE_COMMIT) — rien à faire."
    exit 0
  fi

  echo "Nouveau commit à déployer : $REMOTE_COMMIT (précédent déploiement : ${DEPLOYED_COMMIT:-aucun})"

  if ! git pull origin main --quiet --ff-only; then
    echo "ECHEC : git pull (divergence locale ? conflits ?) — déploiement annulé."
    "$REPO_DIR/scripts/notify_deploy.sh" "Echec git pull vers $REMOTE_COMMIT — verification manuelle necessaire sur le NAS."
    exit 1
  fi

  SHORT_SHA="${REMOTE_COMMIT:0:12}"
  NEW_TAG="$IMAGE_REPO:$SHORT_SHA"

  echo "Reconstruction de l'image backend..."
  export APP_VERSION="$(cat VERSION 2>/dev/null || echo "0.0.0-dev")"
  if ! "$DOCKER" compose -f "$COMPOSE_FILE" build backend; then
    echo "ECHEC : build de l'image backend — l'ancien conteneur continue de tourner, rien n'est coupé."
    "$REPO_DIR/scripts/notify_deploy.sh" "Echec build Docker pour $REMOTE_COMMIT — ancienne version toujours active, verification necessaire."
    exit 1
  fi

  # Tag permanent (survit aux futurs rebuilds qui écrasent IMAGE_REPO:latest) —
  # permet un rollback manuel via `docker tag rescuegrid-backend:<ancien_sha> rescuegrid-backend:latest`.
  "$DOCKER" tag "$IMAGE_REPO:latest" "$NEW_TAG"

  echo "Garde de tests : exécution de la suite de tests contre la nouvelle image (isolée, SQLite jetable)..."
  if ! "$DOCKER" run --rm --entrypoint python "$NEW_TAG" tests/run_tests.py; then
    echo "ECHEC : la suite de tests a échoué sur la nouvelle image — déploiement annulé, l'ancien conteneur continue de tourner."
    "$REPO_DIR/scripts/notify_deploy.sh" "Echec des tests pour $REMOTE_COMMIT — deploiement annule, ancienne version toujours active."
    "$DOCKER" rmi "$NEW_TAG" > /dev/null 2>&1 || true
    exit 1
  fi

  # Lecture directe de .env (et non simple `source`, qui échouerait sur les
  # lignes commentées/valeurs à espaces) pour reconstruire DATABASE_URL, comme
  # le fait docker-compose pour le conteneur backend (voir
  # docker-compose.synology.yml). Nécessaire ici : `docker run` (contrairement
  # à `docker compose up`) n'effectue aucune substitution de variables.
  _env_var() {
    local key="$1" default="$2"
    local raw
    raw="$(grep -m1 "^${key}=" .env 2>/dev/null | cut -d= -f2-)"
    raw="${raw%\"}"
    raw="${raw#\"}"
    echo "${raw:-$default}"
  }
  PG_USER="$(_env_var POSTGRES_USER rescuegrid)"
  PG_PASSWORD="$(_env_var POSTGRES_PASSWORD "")"
  PG_DB="$(_env_var POSTGRES_DB rescuegrid)"

  echo "Application des migrations Alembic (avant bascule du conteneur)..."
  if ! "$DOCKER" run --rm --network "$NETWORK" --env-file .env \
        -e DATABASE_URL="postgresql://${PG_USER}:${PG_PASSWORD}@postgres:5432/${PG_DB}" \
        "$NEW_TAG" alembic upgrade head; then
    echo "ECHEC : migration Alembic — VERIFICATION MANUELLE URGENTE (schema potentiellement incoherent)."
    "$REPO_DIR/scripts/notify_deploy.sh" "ECHEC migration Alembic pour $REMOTE_COMMIT — VERIFICATION URGENTE REQUISE."
    exit 1
  fi

  # Sauvegarde le tag actuellement déployé pour un rollback automatique rapide
  # si la bascule échoue ci-dessous (image seule — la migration n'est pas
  # annulée automatiquement, voir le commentaire en tête de fichier).
  PREVIOUS_SHA="$DEPLOYED_COMMIT"

  echo "Bascule du conteneur backend sur la nouvelle image..."
  if ! "$DOCKER" compose -f "$COMPOSE_FILE" up -d backend; then
    echo "ECHEC : bascule du conteneur backend."
    "$REPO_DIR/scripts/notify_deploy.sh" "Echec bascule backend pour $REMOTE_COMMIT — verification manuelle necessaire."
    exit 1
  fi

  # Sur NAS Synology, uvicorn peut mettre >8s (cold start + init DB/schedulers).
  # On retry /health pendant ~90s au lieu d'un seul sleep court.
  echo "Attente du démarrage puis vérification de santé (/health, max ~90s)..."
  HEALTH_OK=0
  for i in $(seq 1 18); do
    sleep 5
    if curl -sf -m 10 http://127.0.0.1:8080/health > /dev/null; then
      HEALTH_OK=1
      echo "Health OK après ~$((i * 5))s."
      break
    fi
    echo "  tentative $i/18 : /health pas encore prêt..."
  done
  if [ "$HEALTH_OK" -ne 1 ]; then
    echo "ECHEC : /health ne répond pas après bascule."
    if [ -n "$PREVIOUS_SHA" ] && "$DOCKER" image inspect "$IMAGE_REPO:${PREVIOUS_SHA:0:12}" > /dev/null 2>&1; then
      echo "Rollback automatique vers l'image précédente ($PREVIOUS_SHA)..."
      "$DOCKER" tag "$IMAGE_REPO:${PREVIOUS_SHA:0:12}" "$IMAGE_REPO:latest"
      "$DOCKER" compose -f "$COMPOSE_FILE" up -d backend
      sleep 5
      if curl -sf -m 15 http://127.0.0.1:8080/health > /dev/null; then
        echo "Rollback réussi — backend de nouveau opérationnel avec l'ancienne image."
        "$REPO_DIR/scripts/notify_deploy.sh" "Deploiement de $REMOTE_COMMIT en echec (healthcheck) — rollback automatique reussi vers $PREVIOUS_SHA. Migration NON annulee, verification necessaire."
      else
        echo "ECHEC : rollback automatique lui-même en échec."
        "$REPO_DIR/scripts/notify_deploy.sh" "ECHEC CRITIQUE : deploiement de $REMOTE_COMMIT et rollback automatique tous deux en echec — INTERVENTION MANUELLE URGENTE."
      fi
    else
      echo "Pas d'image précédente disponible pour un rollback automatique."
      "$REPO_DIR/scripts/notify_deploy.sh" "Backend indisponible apres deploiement de $REMOTE_COMMIT (pas de rollback possible) — VERIFICATION URGENTE REQUISE."
    fi
    exit 1
  fi

  echo "$REMOTE_COMMIT" > "$MARKER_FILE"
  COMMIT_SUBJECT="$(git log -1 --pretty=%s "$REMOTE_COMMIT")"
  echo "Déploiement réussi : $REMOTE_COMMIT ($COMMIT_SUBJECT)"
  "$REPO_DIR/scripts/notify_deploy.sh" "Deploiement reussi : $COMMIT_SUBJECT"

  echo "Nettoyage des anciennes images taguées (conserve les $KEEP_IMAGES plus récentes)..."
  "$DOCKER" images "$IMAGE_REPO" --format '{{.Tag}} {{.CreatedAt}}' \
    | grep -v '^latest ' \
    | sort -k2 -r \
    | tail -n +"$((KEEP_IMAGES + 1))" \
    | awk '{print $1}' \
    | while read -r old_tag; do
        "$DOCKER" rmi "$IMAGE_REPO:$old_tag" > /dev/null 2>&1 || true
      done
} >> "$LOG_FILE" 2>&1

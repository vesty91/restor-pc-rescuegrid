#!/bin/bash
# nas_auto_deploy.sh — déploiement continu (CD) pour le NAS Synology
# ---------------------------------------------------------------------------
# À exécuter périodiquement (toutes les ~15 min) via le Planificateur de
# tâches Synology — voir docs/SYNOLOGY_DEPLOY.md.
#
# Séquence :
#   1. build image taguée UNIQUEMENT :sha (pas encore :latest)
#   2. garde de tests (run_tests + pytest) sur cette image
#   3. pg_dump pré-migration (annule si dump KO / vide)
#   4. alembic upgrade head
#   5. tag :sha → :latest puis bascule conteneur
#   6. vérification /ready uniquement (pas de fallback /health si DB KO)
#   7. rollback image si /ready échoue (migration NON annulée — dump dispo)
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
KEEP_IMAGES=10
KEEP_PREDEPLOY=10
PREDEPLOY_DIR="$REPO_DIR/volumes/storage/backups"

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

  if [ "${NAS_DEPLOY_REEXEC:-}" != "1" ]; then
    echo "Rechargement du script de déploiement (post git pull)..."
    export NAS_DEPLOY_REEXEC=1
    exec bash "$REPO_DIR/scripts/nas_auto_deploy.sh"
  fi

  SHORT_SHA="${REMOTE_COMMIT:0:12}"
  NEW_TAG="$IMAGE_REPO:$SHORT_SHA"

  echo "Reconstruction de l'image backend ($NEW_TAG) — sans toucher :latest..."
  export APP_VERSION="$(cat VERSION 2>/dev/null || echo "0.0.0-dev")"
  if ! "$DOCKER" build \
        -t "$NEW_TAG" \
        --build-arg "APP_VERSION=$APP_VERSION" \
        -f backend/Dockerfile \
        backend/; then
    echo "ECHEC : build de l'image backend — l'ancien conteneur continue de tourner."
    "$REPO_DIR/scripts/notify_deploy.sh" "Echec build Docker pour $REMOTE_COMMIT — ancienne version toujours active."
    exit 1
  fi

  echo "Garde de tests : run_tests.py contre $NEW_TAG..."
  if ! "$DOCKER" run --rm --entrypoint python "$NEW_TAG" tests/run_tests.py; then
    echo "ECHEC : run_tests.py a échoué — déploiement annulé."
    "$REPO_DIR/scripts/notify_deploy.sh" "Echec des tests (run_tests) pour $REMOTE_COMMIT — deploiement annule."
    "$DOCKER" rmi "$NEW_TAG" > /dev/null 2>&1 || true
    exit 1
  fi

  echo "Garde de tests : pytest unitaire contre $NEW_TAG..."
  if ! "$DOCKER" run --rm --entrypoint python "$NEW_TAG" -m pytest tests/test_unit_pytest.py -q; then
    echo "ECHEC : pytest a échoué — déploiement annulé."
    "$REPO_DIR/scripts/notify_deploy.sh" "Echec des tests (pytest) pour $REMOTE_COMMIT — deploiement annule."
    "$DOCKER" rmi "$NEW_TAG" > /dev/null 2>&1 || true
    exit 1
  fi

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

  mkdir -p "$PREDEPLOY_DIR"
  DUMP_NAME="predeploy_${SHORT_SHA}_$(date +%Y%m%d_%H%M%S).dump"
  DUMP_HOST="$PREDEPLOY_DIR/$DUMP_NAME"
  echo "Sauvegarde PostgreSQL pré-migration → $DUMP_NAME ..."
  if ! "$DOCKER" run --rm --network "$NETWORK" \
        -e PGPASSWORD="$PG_PASSWORD" \
        -v "$PREDEPLOY_DIR:/backups" \
        --entrypoint pg_dump \
        "$NEW_TAG" \
        -h postgres -U "$PG_USER" -Fc -f "/backups/$DUMP_NAME" "$PG_DB"; then
    echo "ECHEC : pg_dump pré-migration — déploiement annulé, schéma inchangé."
    "$REPO_DIR/scripts/notify_deploy.sh" "Echec pg_dump pre-migration pour $REMOTE_COMMIT — deploiement annule."
    exit 1
  fi
  if [ ! -f "$DUMP_HOST" ] || [ ! -s "$DUMP_HOST" ]; then
    echo "ECHEC : dump pré-migration absent ou vide ($DUMP_HOST)."
    "$REPO_DIR/scripts/notify_deploy.sh" "Dump pre-migration vide/absent pour $REMOTE_COMMIT — deploiement annule."
    exit 1
  fi
  echo "Dump OK ($(wc -c < "$DUMP_HOST") octets)."

  # Rotation des dumps pré-déploiement (indépendante des backups quotidiens).
  ls -1t "$PREDEPLOY_DIR"/predeploy_*.dump 2>/dev/null \
    | tail -n +"$((KEEP_PREDEPLOY + 1))" \
    | while read -r old_dump; do
        rm -f "$old_dump" || true
      done

  echo "Application des migrations Alembic (avant bascule)..."
  if ! "$DOCKER" run --rm --network "$NETWORK" --env-file .env \
        -e DATABASE_URL="postgresql://${PG_USER}:${PG_PASSWORD}@postgres:5432/${PG_DB}" \
        --entrypoint alembic \
        "$NEW_TAG" upgrade head; then
    echo "ECHEC : migration Alembic — schéma potentiellement incohérent ; dump dispo : $DUMP_NAME"
    "$REPO_DIR/scripts/notify_deploy.sh" "ECHEC migration Alembic pour $REMOTE_COMMIT — dump $DUMP_NAME disponible — VERIFICATION URGENTE."
    exit 1
  fi

  PREVIOUS_SHA="$DEPLOYED_COMMIT"

  echo "Promotion $NEW_TAG → $IMAGE_REPO:latest puis bascule conteneur..."
  "$DOCKER" tag "$NEW_TAG" "$IMAGE_REPO:latest"
  if ! "$DOCKER" compose -f "$COMPOSE_FILE" up -d backend; then
    echo "ECHEC : bascule du conteneur backend."
    "$REPO_DIR/scripts/notify_deploy.sh" "Echec bascule backend pour $REMOTE_COMMIT — verification manuelle necessaire."
    exit 1
  fi

  # /ready uniquement. Fallback /health seulement si /ready renvoie 404 (vieux backend).
  _ready_ok() {
    local code
    code="$("$DOCKER" compose -f "$COMPOSE_FILE" exec -T backend \
      curl -s -o /dev/null -w "%{http_code}" -m 8 http://127.0.0.1:8000/ready 2>/dev/null || echo "000")"
    if [ "$code" = "200" ]; then
      return 0
    fi
    if [ "$code" = "404" ]; then
      "$DOCKER" compose -f "$COMPOSE_FILE" exec -T backend \
        curl -sf -m 8 http://127.0.0.1:8000/health > /dev/null 2>&1 && return 0
    fi
    code="$(curl -s -o /dev/null -w "%{http_code}" -m 8 http://127.0.0.1:8080/ready 2>/dev/null || echo "000")"
    if [ "$code" = "200" ]; then
      return 0
    fi
    if [ "$code" = "404" ]; then
      curl -sf -m 8 http://127.0.0.1:8080/health > /dev/null 2>&1 && return 0
    fi
    return 1
  }

  echo "Attente readiness (/ready, max ~120s)..."
  HEALTH_OK=0
  for i in $(seq 1 24); do
    sleep 5
    if _ready_ok; then
      HEALTH_OK=1
      echo "Ready OK après ~$((i * 5))s."
      break
    fi
    echo "  tentative $i/24 : /ready pas encore prêt..."
  done
  if [ "$HEALTH_OK" -ne 1 ]; then
    echo "ECHEC : /ready ne répond pas après bascule."
    echo "--- docker compose ps ---"
    "$DOCKER" compose -f "$COMPOSE_FILE" ps || true
    echo "--- logs backend (80 dernières lignes) ---"
    "$DOCKER" compose -f "$COMPOSE_FILE" logs --tail=80 backend || true
    if [ -n "$PREVIOUS_SHA" ] && "$DOCKER" image inspect "$IMAGE_REPO:${PREVIOUS_SHA:0:12}" > /dev/null 2>&1; then
      echo "Rollback automatique vers l'image précédente ($PREVIOUS_SHA)..."
      "$DOCKER" tag "$IMAGE_REPO:${PREVIOUS_SHA:0:12}" "$IMAGE_REPO:latest"
      "$DOCKER" compose -f "$COMPOSE_FILE" up -d backend
      ROLLBACK_OK=0
      for j in $(seq 1 18); do
        sleep 5
        if _ready_ok; then
          ROLLBACK_OK=1
          break
        fi
      done
      if [ "$ROLLBACK_OK" -eq 1 ]; then
        echo "Rollback réussi — dump pré-migration : $DUMP_NAME (migration NON annulée)."
        "$REPO_DIR/scripts/notify_deploy.sh" "Deploiement $REMOTE_COMMIT echec /ready — rollback image OK. Dump $DUMP_NAME. Migration NON annulee."
      else
        echo "ECHEC : rollback automatique lui-même en échec."
        "$REPO_DIR/scripts/notify_deploy.sh" "ECHEC CRITIQUE : deploiement $REMOTE_COMMIT et rollback en echec — dump $DUMP_NAME — INTERVENTION URGENTE."
      fi
    else
      echo "Pas d'image précédente pour rollback."
      "$REPO_DIR/scripts/notify_deploy.sh" "Backend indisponible apres $REMOTE_COMMIT (pas de rollback) — dump $DUMP_NAME — VERIFICATION URGENTE."
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

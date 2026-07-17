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
# Sûr par construction : n'avance le marqueur .last_deployed_commit qu'après
# un déploiement intégralement réussi (build + migration + healthcheck) ; en
# cas d'échec à n'importe quelle étape, l'ancien conteneur continue de tourner
# sans interruption et une alerte ntfy est envoyée (voir notify_deploy.sh).
set -uo pipefail

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_DIR" || exit 1

LOG_DIR="$REPO_DIR/logs"
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/auto_deploy.log"
MARKER_FILE="$REPO_DIR/.last_deployed_commit"
COMPOSE_FILE="docker-compose.synology.yml"
DOCKER="/usr/local/bin/docker"

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

  echo "Reconstruction de l'image backend..."
  if ! "$DOCKER" compose -f "$COMPOSE_FILE" build backend; then
    echo "ECHEC : build de l'image backend — l'ancien conteneur continue de tourner, rien n'est coupé."
    "$REPO_DIR/scripts/notify_deploy.sh" "Echec build Docker pour $REMOTE_COMMIT — ancienne version toujours active, verification necessaire."
    exit 1
  fi

  echo "Redémarrage du conteneur backend..."
  if ! "$DOCKER" compose -f "$COMPOSE_FILE" up -d backend; then
    echo "ECHEC : redémarrage du conteneur backend."
    "$REPO_DIR/scripts/notify_deploy.sh" "Echec redemarrage backend pour $REMOTE_COMMIT — verification manuelle necessaire."
    exit 1
  fi

  echo "Attente du démarrage (8s) puis application des migrations Alembic..."
  sleep 8
  if ! "$DOCKER" exec rescuegrid_backend alembic upgrade head; then
    echo "ECHEC : migration Alembic — VERIFICATION MANUELLE URGENTE (le conteneur tourne peut-être avec un schéma désynchronisé)."
    "$REPO_DIR/scripts/notify_deploy.sh" "ECHEC migration Alembic pour $REMOTE_COMMIT — VERIFICATION URGENTE REQUISE."
    exit 1
  fi

  echo "Vérification de santé post-déploiement..."
  if ! curl -sf -m 15 http://127.0.0.1:8080/health > /dev/null; then
    echo "ECHEC : /health ne répond pas après déploiement — VERIFICATION MANUELLE URGENTE."
    "$REPO_DIR/scripts/notify_deploy.sh" "Backend indisponible apres deploiement de $REMOTE_COMMIT — VERIFICATION URGENTE REQUISE."
    exit 1
  fi

  echo "$REMOTE_COMMIT" > "$MARKER_FILE"
  COMMIT_SUBJECT="$(git log -1 --pretty=%s "$REMOTE_COMMIT")"
  echo "Déploiement réussi : $REMOTE_COMMIT ($COMMIT_SUBJECT)"
  "$REPO_DIR/scripts/notify_deploy.sh" "Deploiement reussi : $COMMIT_SUBJECT"
} >> "$LOG_FILE" 2>&1

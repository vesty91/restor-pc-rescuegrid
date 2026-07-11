"""
backup.py — Restor-PC RescueGrid v12.3
---------------------------------------
Sauvegarde planifiée de la base de données avec rotation.

- SQLite (dev / petites installations) : copie simple du fichier .db.
- PostgreSQL (Synology / prod) : dump via `pg_dump` (nécessite le paquet
  postgresql-client dans l'image Docker — voir backend/Dockerfile).

Le scheduler tourne en tâche de fond asyncio, sans dépendance supplémentaire
(pas d'APScheduler) : il dort jusqu'à la prochaine heure planifiée (UTC) puis
déclenche perform_backup_and_rotate(). En cas d'erreur, il retente 1h plus tard
plutôt que de s'arrêter définitivement.
"""
from __future__ import annotations

import asyncio
import logging
import os
import shutil
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse

from .database import DATABASE_URL

logger = logging.getLogger(__name__)

BACKUP_SCHEDULE_ENABLED = os.getenv("BACKUP_SCHEDULE_ENABLED", "true").strip().lower() in {"1", "true", "yes"}
BACKUP_SCHEDULE_HOUR = int(os.getenv("BACKUP_SCHEDULE_HOUR", "3"))
BACKUP_RETENTION_COUNT = int(os.getenv("BACKUP_RETENTION_COUNT", "14"))

_PREFIX = "rescuegrid_"


def _backup_dir(storage_dir: Path) -> Path:
    d = storage_dir / "backups"
    d.mkdir(parents=True, exist_ok=True)
    return d


def is_postgres() -> bool:
    return DATABASE_URL.startswith("postgresql://")


def _sqlite_db_path(base_dir: Path) -> Path | None:
    for name in ["rescuegrid.db", "app.db"]:
        p = base_dir / name
        if p.exists():
            return p
    return None


def _dump_postgres(destination: Path) -> None:
    parsed = urlparse(DATABASE_URL)
    env = dict(os.environ)
    if parsed.password:
        env["PGPASSWORD"] = parsed.password
    dbname = (parsed.path or "/").lstrip("/") or "postgres"
    cmd = [
        "pg_dump",
        "-h", parsed.hostname or "localhost",
        "-p", str(parsed.port or 5432),
        "-U", parsed.username or "postgres",
        "-F", "p",
        "-f", str(destination),
        dbname,
    ]
    try:
        result = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=300)
    except FileNotFoundError as exc:
        raise RuntimeError(
            "pg_dump introuvable — installez le paquet postgresql-client (voir Dockerfile)."
        ) from exc
    if result.returncode != 0:
        raise RuntimeError(f"pg_dump a échoué : {result.stderr.strip()}")


def perform_backup_and_rotate(base_dir: Path, storage_dir: Path) -> Path:
    """Effectue une sauvegarde immédiate puis applique la rotation. Retourne le fichier créé."""
    backups_dir = _backup_dir(storage_dir)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")

    if is_postgres():
        destination = backups_dir / f"{_PREFIX}{timestamp}.sql"
        _dump_postgres(destination)
    else:
        source = _sqlite_db_path(base_dir)
        if not source:
            raise FileNotFoundError("Base SQLite introuvable pour la sauvegarde")
        destination = backups_dir / f"{_PREFIX}{timestamp}.db"
        shutil.copy2(source, destination)

    logger.info("Sauvegarde créée : %s", destination.name)
    _rotate_backups(backups_dir)
    return destination


def _rotate_backups(backups_dir: Path) -> None:
    files = sorted(
        (p for p in backups_dir.iterdir() if p.is_file() and p.name.startswith(_PREFIX)),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    for stale in files[BACKUP_RETENTION_COUNT:]:
        try:
            stale.unlink()
            logger.info("Sauvegarde expirée supprimée (rétention %d) : %s", BACKUP_RETENTION_COUNT, stale.name)
        except OSError as exc:
            logger.warning("Impossible de supprimer %s : %s", stale.name, exc)


def _human_size(num_bytes: int) -> str:
    size = float(num_bytes)
    for unit in ["o", "Ko", "Mo", "Go"]:
        if size < 1024 or unit == "Go":
            return f"{size:.1f} {unit}" if unit != "o" else f"{int(size)} {unit}"
        size /= 1024
    return f"{size:.1f} Go"


def list_backups(storage_dir: Path) -> list[dict]:
    backups_dir = _backup_dir(storage_dir)
    files = sorted(
        (p for p in backups_dir.iterdir() if p.is_file() and p.name.startswith(_PREFIX)),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    return [
        {
            "name": p.name,
            "size_bytes": p.stat().st_size,
            "size_human": _human_size(p.stat().st_size),
            "created_at": datetime.fromtimestamp(p.stat().st_mtime, tz=timezone.utc),
        }
        for p in files
    ]


def _seconds_until_next_run() -> float:
    now = datetime.now(timezone.utc)
    target = now.replace(hour=BACKUP_SCHEDULE_HOUR, minute=0, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    return (target - now).total_seconds()


async def _backup_scheduler_loop(base_dir: Path, storage_dir: Path) -> None:
    while True:
        try:
            delay = _seconds_until_next_run()
            logger.info("Prochaine sauvegarde planifiée dans %.0f minutes", delay / 60)
            await asyncio.sleep(delay)
            perform_backup_and_rotate(base_dir, storage_dir)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Échec de la sauvegarde planifiée — nouvelle tentative dans 1h")
            await asyncio.sleep(3600)


def start_backup_scheduler(base_dir: Path, storage_dir: Path) -> "asyncio.Task | None":
    if not BACKUP_SCHEDULE_ENABLED:
        logger.info("Sauvegarde planifiée désactivée (BACKUP_SCHEDULE_ENABLED=false)")
        return None
    logger.info(
        "Sauvegarde planifiée activée — heure cible %02d:00 UTC, rétention %d copies",
        BACKUP_SCHEDULE_HOUR, BACKUP_RETENTION_COUNT,
    )
    return asyncio.create_task(_backup_scheduler_loop(base_dir, storage_dir))

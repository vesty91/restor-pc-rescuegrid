"""
backup.py — Restor-PC RescueGrid
---------------------------------------
Sauvegarde planifiée de la base de données avec rotation.

- SQLite (dev / petites installations) : copie cohérente via
  sqlite3.Connection.backup() (évite une sauvegarde corrompue si la base
  est en cours d'écriture pendant le backup).
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
import sqlite3
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse

from .database import DATABASE_URL

logger = logging.getLogger(__name__)

BACKUP_SCHEDULE_ENABLED = os.getenv("BACKUP_SCHEDULE_ENABLED", "true").strip().lower() in {"1", "true", "yes"}
BACKUP_SCHEDULE_HOUR = int(os.getenv("BACKUP_SCHEDULE_HOUR", "3"))
BACKUP_RETENTION_COUNT = int(os.getenv("BACKUP_RETENTION_COUNT", "14"))
BACKUP_ALERT_EMAIL = os.getenv("BACKUP_ALERT_EMAIL", "").strip()
# Notification push (ntfy.sh ou serveur ntfy auto-hébergé) : alternative/complément
# à l'email, quasi instantanée sur mobile/desktop. URL complète du topic, ex.
# https://ntfy.sh/mon-topic-secret ou https://ntfy.mondomaine.fr/mon-topic.
BACKUP_ALERT_NTFY_URL = os.getenv("BACKUP_ALERT_NTFY_URL", "").strip()

_PREFIX = "rescuegrid_"


def _backup_dir(storage_dir: Path) -> Path:
    d = storage_dir / "backups"
    d.mkdir(parents=True, exist_ok=True)
    return d


def is_postgres() -> bool:
    return DATABASE_URL.startswith("postgresql")


def _sqlite_db_path(base_dir: Path) -> Path | None:
    """Chemin réel de la base SQLite depuis DATABASE_URL (pas seulement rescuegrid.db)."""
    from sqlalchemy.engine.url import make_url

    try:
        url = make_url(DATABASE_URL)
    except Exception:
        return None
    if url.get_backend_name() != "sqlite":
        return None
    db = url.database
    if not db or db == ":memory:":
        return None
    source = Path(db)
    if not source.is_absolute():
        source = (base_dir / source).resolve()
    else:
        source = source.resolve()
    return source if source.exists() else None


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


def _dump_sqlite(source: Path, destination: Path) -> None:
    """Copie cohérente d'une base SQLite (API backup native, pas un shutil.copy2)."""
    src = sqlite3.connect(f"file:{source}?mode=ro", uri=True)
    try:
        dst = sqlite3.connect(destination)
        try:
            src.backup(dst)
        finally:
            dst.close()
    finally:
        src.close()


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
        _dump_sqlite(source, destination)

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


def _send_backup_alert_ntfy(error_message: str) -> None:
    """Notification push best-effort via ntfy (https://ntfy.sh ou serveur
    auto-hébergé) : alternative à l'email, quasi instantanée sur mobile grâce à
    l'app ntfy. Utilise httpx (déjà une dépendance du projet, voir app/oauth.py)
    plutôt que d'ajouter `requests`."""
    if not BACKUP_ALERT_NTFY_URL:
        return
    try:
        import httpx

        httpx.post(
            BACKUP_ALERT_NTFY_URL,
            content=f"Erreur : {error_message}\n\nNouvelle tentative automatique dans 1h.".encode("utf-8"),
            headers={
                "Title": "RescueGrid - Echec sauvegarde",
                "Priority": "urgent",
                "Tags": "warning,rescuegrid",
            },
            timeout=10,
        )
    except Exception:
        logger.exception("Échec de l'envoi de l'alerte ntfy de sauvegarde")


def _send_backup_alert(error_message: str) -> None:
    """Alerte (email et/ou ntfy) best-effort en cas d'échec de sauvegarde
    planifiée — sans cela, un échec (ex. incompatibilité de version pg_dump/
    serveur) peut passer inaperçu pendant des mois, les seules traces étant des
    logs applicatifs que personne ne consulte au quotidien. N'est jamais
    bloquant : une alerte ratée ne doit pas empêcher la nouvelle tentative de
    sauvegarde 1h plus tard (voir _backup_scheduler_loop)."""
    _send_backup_alert_ntfy(error_message)
    if not BACKUP_ALERT_EMAIL:
        return
    try:
        import smtplib
        from email.message import EmailMessage
        from email.utils import formataddr

        # Import tardif : évite tout import circulaire au chargement du module
        # (routes_v10.py importe déjà des éléments d'app.models/app.database).
        from .services.mail import smtp_config as _smtp_config

        cfg = _smtp_config()
        if not cfg["enabled"] or not cfg["password"]:
            return

        msg = EmailMessage()
        msg["From"] = formataddr((cfg["from_name"], cfg["sender"]))
        msg["To"] = BACKUP_ALERT_EMAIL
        msg["Subject"] = "Alerte RescueGrid - echec de la sauvegarde planifiee"
        msg.set_content(
            "La sauvegarde automatique planifiee de RescueGrid a echoue.\n\n"
            f"Erreur : {error_message}\n\n"
            "Une nouvelle tentative aura lieu automatiquement dans 1 heure. "
            "Si l'erreur persiste, une intervention manuelle est necessaire "
            "(voir les logs du conteneur backend)."
        )
        if cfg["use_ssl"]:
            with smtplib.SMTP_SSL(cfg["host"], cfg["port"], timeout=30) as smtp:
                smtp.login(cfg["user"], cfg["password"])
                smtp.send_message(msg)
        else:
            with smtplib.SMTP(cfg["host"], cfg["port"], timeout=30) as smtp:
                smtp.ehlo()
                if cfg["use_tls"]:
                    smtp.starttls()
                    smtp.ehlo()
                smtp.login(cfg["user"], cfg["password"])
                smtp.send_message(msg)
    except Exception:
        logger.exception("Échec de l'envoi de l'alerte email de sauvegarde")


def _seconds_until_next_run() -> float:
    now = datetime.now(timezone.utc)
    target = now.replace(hour=BACKUP_SCHEDULE_HOUR, minute=0, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    return (target - now).total_seconds()


async def _backup_scheduler_loop(base_dir: Path, storage_dir: Path) -> None:
    import os
    from .rate_limit import release_scheduler_lock, try_acquire_scheduler_lock

    holder = f"pid-{os.getpid()}"
    while True:
        try:
            delay = _seconds_until_next_run()
            logger.info("Prochaine sauvegarde planifiée dans %.0f minutes", delay / 60)
            await asyncio.sleep(delay)
            if not try_acquire_scheduler_lock("backup", holder, ttl_seconds=600):
                logger.info("Sauvegarde planifiée déjà en cours sur un autre worker — skip")
                continue
            try:
                perform_backup_and_rotate(base_dir, storage_dir)
            finally:
                release_scheduler_lock("backup", holder)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.exception("Échec de la sauvegarde planifiée — nouvelle tentative dans 1h")
            _send_backup_alert(str(exc))
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

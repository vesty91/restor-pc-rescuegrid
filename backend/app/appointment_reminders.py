"""
appointment_reminders.py — Rappels automatiques RDV (J-1)
---------------------------------------------------------
Boucle asyncio calquée sur reminders_scheduler.py.
Fenêtre par défaut : 20–28 h avant start_at (≈ rappel la veille).
Désactivé tant que APPOINTMENT_REMINDER_ENABLED n'est pas true.
"""
from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from .database import SessionLocal
from .models import Appointment

logger = logging.getLogger(__name__)

APPOINTMENT_REMINDER_ENABLED = os.getenv("APPOINTMENT_REMINDER_ENABLED", "false").strip().lower() in {
    "1",
    "true",
    "yes",
}
APPOINTMENT_REMINDER_HOURS_MIN = float(os.getenv("APPOINTMENT_REMINDER_HOURS_MIN", "20"))
APPOINTMENT_REMINDER_HOURS_MAX = float(os.getenv("APPOINTMENT_REMINDER_HOURS_MAX", "28"))
APPOINTMENT_REMINDER_POLL_SECONDS = int(os.getenv("APPOINTMENT_REMINDER_POLL_SECONDS", "900"))

_ACTIVE_STATUSES = ("scheduled", "confirmed")

# Canaux définitivement inutilisables (pas la peine de reboucler).
_DEAD_MAIL = frozenset({"no_client", "missing_client_email"})
_DEAD_SMS = frozenset({"no_client", "missing_client_phone", "sms_not_configured", None})


def _reminder_succeeded(mail_detail: str | None, sms_detail: str | None) -> bool:
    return mail_detail == "sent" or sms_detail == "sent"


def _reminder_permanently_unusable(mail_detail: str | None, sms_detail: str | None) -> bool:
    return mail_detail in _DEAD_MAIL and sms_detail in _DEAD_SMS


def run_due_appointment_reminders() -> int:
    """Envoie les rappels J-1 dus. Retourne le nombre de RDV marqués (succès ou dead-end)."""
    from .routes.planning import _notify_client_appointment, _notify_client_appointment_sms

    now = datetime.now(timezone.utc)
    window_start = now + timedelta(hours=APPOINTMENT_REMINDER_HOURS_MIN)
    window_end = now + timedelta(hours=APPOINTMENT_REMINDER_HOURS_MAX)
    marked = 0

    with SessionLocal() as session:
        due = session.scalars(
            select(Appointment).where(
                Appointment.reminder_opt_in.is_(True),
                Appointment.sms_reminder_sent_at.is_(None),
                Appointment.status.in_(_ACTIVE_STATUSES),
                Appointment.start_at >= window_start,
                Appointment.start_at < window_end,
            )
        ).all()

        for appointment in due:
            mail_detail = _notify_client_appointment(session, appointment, event="reminder")
            sms_detail = _notify_client_appointment_sms(session, appointment, event="reminder")

            if _reminder_succeeded(mail_detail, sms_detail):
                appointment.sms_reminder_sent_at = now
                session.commit()
                marked += 1
                logger.info(
                    "Rappel RDV %s envoyé (mail=%s sms=%s)",
                    appointment.id,
                    mail_detail,
                    sms_detail,
                )
            elif _reminder_permanently_unusable(mail_detail, sms_detail):
                # Aucun canal ne pourra jamais réussir — évite une boucle infinie.
                appointment.sms_reminder_sent_at = now
                session.commit()
                marked += 1
                logger.info(
                    "RDV %s : aucun canal utilisable (mail=%s sms=%s) — marqué pour stop retry",
                    appointment.id,
                    mail_detail,
                    sms_detail,
                )
            else:
                # Échec transitoire SMTP/Twilio — retenter au prochain poll.
                logger.warning(
                    "Rappel RDV %s échoué (mail=%s sms=%s) — nouvel essai plus tard",
                    appointment.id,
                    mail_detail,
                    sms_detail,
                )

    if marked:
        logger.info("Rappels RDV automatiques : %d traités", marked)
    return marked


async def _appointment_reminder_loop() -> None:
    from .rate_limit import release_scheduler_lock, try_acquire_scheduler_lock

    holder = f"pid-{os.getpid()}"
    while True:
        try:
            if try_acquire_scheduler_lock("appointment_reminders", holder, ttl_seconds=600):
                try:
                    run_due_appointment_reminders()
                finally:
                    release_scheduler_lock("appointment_reminders", holder)
            else:
                logger.debug("Rappels RDV déjà en cours sur un autre worker — skip")
            await asyncio.sleep(APPOINTMENT_REMINDER_POLL_SECONDS)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Échec balayage rappels RDV — nouvel essai dans 15 min")
            await asyncio.sleep(900)


def start_appointment_reminder_scheduler() -> "asyncio.Task | None":
    if not APPOINTMENT_REMINDER_ENABLED:
        logger.info(
            "Rappels RDV J-1 désactivés (APPOINTMENT_REMINDER_ENABLED=false) — "
            "activation via .env + Twilio/SMTP"
        )
        return None
    logger.info(
        "Rappels RDV J-1 activés — fenêtre %.0f–%.0f h avant le RDV, poll %ds",
        APPOINTMENT_REMINDER_HOURS_MIN,
        APPOINTMENT_REMINDER_HOURS_MAX,
        APPOINTMENT_REMINDER_POLL_SECONDS,
    )
    return asyncio.create_task(_appointment_reminder_loop())

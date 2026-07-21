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
# Heures avant le RDV : borne basse / haute de la fenêtre d'envoi
APPOINTMENT_REMINDER_HOURS_MIN = float(os.getenv("APPOINTMENT_REMINDER_HOURS_MIN", "20"))
APPOINTMENT_REMINDER_HOURS_MAX = float(os.getenv("APPOINTMENT_REMINDER_HOURS_MAX", "28"))
# Intervalle entre deux balayages (secondes)
APPOINTMENT_REMINDER_POLL_SECONDS = int(os.getenv("APPOINTMENT_REMINDER_POLL_SECONDS", "900"))

_ACTIVE_STATUSES = ("scheduled", "confirmed")


def run_due_appointment_reminders() -> int:
    """Envoie les rappels J-1 dus. Retourne le nombre de RDV notifiés."""
    from .routes.planning import _notify_client_appointment, _notify_client_appointment_sms

    now = datetime.now(timezone.utc)
    window_start = now + timedelta(hours=APPOINTMENT_REMINDER_HOURS_MIN)
    window_end = now + timedelta(hours=APPOINTMENT_REMINDER_HOURS_MAX)
    sent = 0

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
            # Marquer envoyé dès qu'au moins un canal a tenté (évite boucle infinie
            # si email/SMS absents) — sauf si les deux disent "pas de client".
            if mail_detail in {"no_client"} and sms_detail in {"no_client", None}:
                logger.info("RDV %s : pas de client — skip rappel", appointment.id)
                continue
            appointment.sms_reminder_sent_at = now
            session.commit()
            sent += 1
            logger.info(
                "Rappel RDV %s envoyé (mail=%s sms=%s)",
                appointment.id,
                mail_detail,
                sms_detail,
            )

    if sent:
        logger.info("Rappels RDV automatiques : %d envoyés", sent)
    return sent


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

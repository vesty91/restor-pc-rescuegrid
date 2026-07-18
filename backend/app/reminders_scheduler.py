"""
reminders_scheduler.py — Relances automatiques (devis/factures en retard)
---------------------------------------------------------------------------
Par défaut, les relances restent 100% manuelles (bouton sur /relances) comme
avant cette fonctionnalité — voir REMINDER_SCHEDULE_ENABLED. Le pattern est
calqué sur app/backup.py : pas d'APScheduler, juste une tâche de fond asyncio
qui vérifie une fois par jour (à REMINDER_SCHEDULE_HOUR UTC) les devis/factures
en retard et relance ceux qui n'ont pas déjà été relancés depuis moins de
REMINDER_COOLDOWN_DAYS jours.
"""
from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from .database import SessionLocal
from .models import Invoice, Quote, Reminder

logger = logging.getLogger(__name__)

REMINDER_SCHEDULE_ENABLED = os.getenv("REMINDER_SCHEDULE_ENABLED", "false").strip().lower() in {"1", "true", "yes"}
REMINDER_SCHEDULE_HOUR = int(os.getenv("REMINDER_SCHEDULE_HOUR", "8"))
REMINDER_COOLDOWN_DAYS = int(os.getenv("REMINDER_COOLDOWN_DAYS", "7"))


def _last_reminder_at(session, target_type: str, target_id: int) -> datetime | None:
    reminder = session.scalars(
        select(Reminder)
        .where(Reminder.target_type == target_type, Reminder.target_id == target_id)
        .order_by(Reminder.sent_at.desc())
    ).first()
    return reminder.sent_at if reminder else None


def _is_in_cooldown(last_sent_at: datetime | None, cooldown_days: int, now: datetime | None = None) -> bool:
    """True si une relance a déjà été envoyée trop récemment (pas de renvoi)."""
    if last_sent_at is None:
        return False
    now = now or datetime.now(timezone.utc)
    if last_sent_at.tzinfo is None:
        last_sent_at = last_sent_at.replace(tzinfo=timezone.utc)
    return (now - last_sent_at) < timedelta(days=cooldown_days)


def run_due_reminders() -> tuple[int, int]:
    """Envoie les relances dues (hors cooldown) pour tous les devis/factures en
    retard. Retourne (nb_devis_relances, nb_factures_relancees). Fonction
    synchrone réutilisable aussi bien par le scheduler que par un test/appel
    manuel (ex. future route "relancer tout maintenant")."""
    # Import tardif : évite tout import circulaire au chargement du module
    # (routes_v10.py importe déjà des éléments d'app.models/app.database).
    from .services.reminders import send_invoice_reminder, send_quote_reminder

    now = datetime.now(timezone.utc)
    quotes_sent = 0
    invoices_sent = 0

    with SessionLocal() as session:
        overdue_quotes = session.scalars(
            select(Quote).where(Quote.status == "sent", Quote.valid_until.is_not(None), Quote.valid_until < now)
        ).all()
        for quote in overdue_quotes:
            last_sent = _last_reminder_at(session, "quote", quote.id)
            if _is_in_cooldown(last_sent, REMINDER_COOLDOWN_DAYS, now):
                continue
            ok, detail = send_quote_reminder(session, quote, user=None)
            if ok:
                quotes_sent += 1
            else:
                logger.info("Relance auto devis %s non envoyée : %s", quote.quote_number, detail)

        overdue_invoices = session.scalars(
            select(Invoice).where(Invoice.status == "issued", Invoice.due_date.is_not(None), Invoice.due_date < now)
        ).all()
        for invoice in overdue_invoices:
            last_sent = _last_reminder_at(session, "invoice", invoice.id)
            if _is_in_cooldown(last_sent, REMINDER_COOLDOWN_DAYS, now):
                continue
            ok, detail = send_invoice_reminder(session, invoice, user=None)
            if ok:
                invoices_sent += 1
            else:
                logger.info("Relance auto facture %s non envoyée : %s", invoice.invoice_number, detail)

    logger.info("Relances automatiques : %d devis, %d factures relancés", quotes_sent, invoices_sent)
    return quotes_sent, invoices_sent


def _seconds_until_next_run() -> float:
    now = datetime.now(timezone.utc)
    target = now.replace(hour=REMINDER_SCHEDULE_HOUR, minute=0, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    return (target - now).total_seconds()


async def _reminder_scheduler_loop() -> None:
    import os
    from .rate_limit import release_scheduler_lock, try_acquire_scheduler_lock

    holder = f"pid-{os.getpid()}"
    while True:
        try:
            delay = _seconds_until_next_run()
            logger.info("Prochaine vérification des relances automatiques dans %.0f minutes", delay / 60)
            await asyncio.sleep(delay)
            if not try_acquire_scheduler_lock("reminders", holder, ttl_seconds=600):
                logger.info("Relances automatiques déjà en cours sur un autre worker — skip")
                continue
            try:
                run_due_reminders()
            finally:
                release_scheduler_lock("reminders", holder)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Échec de la vérification des relances automatiques — nouvelle tentative dans 1h")
            await asyncio.sleep(3600)


def start_reminder_scheduler() -> "asyncio.Task | None":
    if not REMINDER_SCHEDULE_ENABLED:
        logger.info("Relances automatiques désactivées (REMINDER_SCHEDULE_ENABLED=false) — clic manuel requis sur /relances")
        return None
    logger.info(
        "Relances automatiques activées — vérification quotidienne à %02d:00 UTC, "
        "renvoi au plus tôt %d jours après la dernière relance",
        REMINDER_SCHEDULE_HOUR, REMINDER_COOLDOWN_DAYS,
    )
    return asyncio.create_task(_reminder_scheduler_loop())

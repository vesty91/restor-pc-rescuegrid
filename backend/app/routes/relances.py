"""Page /relances et déclenchement manuel des rappels devis/factures."""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth import get_user_or_redirect
from ..database import get_session
from ..models import Invoice, Quote, Reminder
from ..services.reminders import send_invoice_reminder, send_quote_reminder

router = APIRouter()
_templates: Jinja2Templates | None = None


def init_router(templates: Jinja2Templates) -> APIRouter:
    global _templates
    _templates = templates
    return router


def _last_reminder_at(session: Session, target_type: str, target_id: int):
    return session.scalars(
        select(Reminder)
        .where(Reminder.target_type == target_type, Reminder.target_id == target_id)
        .order_by(Reminder.sent_at.desc())
    ).first()


@router.get("/relances", response_class=HTMLResponse)
def reminders_page(request: Request, session: Session = Depends(get_session)):
    user, redirect = get_user_or_redirect(request, session)
    if redirect:
        return redirect
    now = datetime.now(timezone.utc)
    overdue_quotes = session.scalars(
        select(Quote)
        .where(Quote.status == "sent", Quote.valid_until.is_not(None), Quote.valid_until < now)
        .order_by(Quote.valid_until.asc())
    ).all()
    overdue_invoices = session.scalars(
        select(Invoice)
        .where(Invoice.status == "issued", Invoice.due_date.is_not(None), Invoice.due_date < now)
        .order_by(Invoice.due_date.asc())
    ).all()
    quote_rows = [{
        "quote": q,
        "days_overdue": (now.date() - q.valid_until.date()).days if q.valid_until else 0,
        "last_reminder": _last_reminder_at(session, "quote", q.id),
    } for q in overdue_quotes]
    invoice_rows = [{
        "invoice": inv,
        "days_overdue": (now.date() - inv.due_date.date()).days if inv.due_date else 0,
        "last_reminder": _last_reminder_at(session, "invoice", inv.id),
    } for inv in overdue_invoices]
    from .. import reminders_scheduler
    return _templates.TemplateResponse("relances.html", {
        "active_page": "relances",
        "request": request,
        "user": user,
        "quote_rows": quote_rows,
        "invoice_rows": invoice_rows,
        "reminder_schedule_enabled": reminders_scheduler.REMINDER_SCHEDULE_ENABLED,
        "reminder_schedule_hour": reminders_scheduler.REMINDER_SCHEDULE_HOUR,
        "reminder_cooldown_days": reminders_scheduler.REMINDER_COOLDOWN_DAYS,
    })


@router.post("/quote/{quote_id}/remind")
def remind_quote(quote_id: int, request: Request, session: Session = Depends(get_session)):
    user, redirect = get_user_or_redirect(request, session)
    if redirect:
        return redirect
    quote_obj = session.scalars(select(Quote).where(Quote.id == quote_id)).first()
    if not quote_obj:
        raise HTTPException(status_code=404, detail="Devis introuvable")
    ok, detail = send_quote_reminder(session, quote_obj, user=user)
    if ok:
        return RedirectResponse("/relances?mail=sent", status_code=303)
    if detail == "missing_client_email":
        return RedirectResponse("/relances?mail=missing_client_email", status_code=303)
    return RedirectResponse("/relances?mail=error", status_code=303)


@router.post("/invoice/{invoice_id}/remind")
def remind_invoice(invoice_id: int, request: Request, session: Session = Depends(get_session)):
    user, redirect = get_user_or_redirect(request, session)
    if redirect:
        return redirect
    invoice_obj = session.scalars(select(Invoice).where(Invoice.id == invoice_id)).first()
    if not invoice_obj:
        raise HTTPException(status_code=404, detail="Facture introuvable")
    ok, detail = send_invoice_reminder(session, invoice_obj, user=user)
    if ok:
        return RedirectResponse("/relances?mail=sent", status_code=303)
    if detail == "missing_client_email":
        return RedirectResponse("/relances?mail=missing_client_email", status_code=303)
    return RedirectResponse("/relances?mail=error", status_code=303)

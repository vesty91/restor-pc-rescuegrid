"""
routes/billing.py — Restor-PC RescueGrid v12.3
------------------------------------------------
Factures : GET/POST /invoices, actions statut et suppression.

NOTE : /quotes et ses actions sont dans routes_v10.py (avec log_activity, email, PDF).
       Ce fichier gère uniquement les routes invoices absentes de routes_v10.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_session
from ..deps import get_user_or_redirect
from ..auth import get_admin_or_redirect
from ..helpers import paginate_query
from ..models import Intervention, Invoice

logger = logging.getLogger(__name__)
router = APIRouter()
_templates: Jinja2Templates | None = None
_next_document_number = None
_default_billing_amount = None


def init_router(templates, next_doc_fn, billing_fn) -> APIRouter:
    global _templates, _next_document_number, _default_billing_amount
    _templates = templates
    _next_document_number = next_doc_fn
    _default_billing_amount = billing_fn
    return router


# ── Page liste factures ───────────────────────────────────────────────────────

@router.get("/invoices", response_class=HTMLResponse)
def invoices_list(request: Request, page: int = 1, session: Session = Depends(get_session)):
    user, redirect = get_user_or_redirect(request, session)
    if redirect:
        return redirect
    query = select(Invoice).order_by(Invoice.created_at.desc())
    invoices, page, total_pages, total_items = paginate_query(session, query, page)
    interventions = session.scalars(select(Intervention).order_by(Intervention.created_at.desc())).all()
    return _templates.TemplateResponse("invoices.html", {
        "request": request,
        "user": user,
        "active_page": "invoices",
        "invoices": invoices,
        "interventions": interventions,
        "default_billing_amount": _default_billing_amount,
        "today_date": lambda: datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "page": page,
        "total_pages": total_pages,
        "total_items": total_items,
    })


# ── Créer une facture ─────────────────────────────────────────────────────────

@router.post("/invoices")
def create_invoice(
    request: Request,
    intervention_id: int = Form(...),
    notes: str = Form(""),
    amount: float = Form(...),
    due_date: str = Form(""),
    status: str = Form("draft"),
    session: Session = Depends(get_session),
):
    user, redirect = get_user_or_redirect(request, session)
    if redirect:
        return redirect
    intervention = session.get(Intervention, intervention_id)
    number = _next_document_number(session, "INV", Invoice, "invoice_number")
    due = None
    if due_date:
        try:
            due = datetime.strptime(due_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    invoice = Invoice(
        intervention_id=intervention_id,
        client_id=intervention.client_id if intervention else None,
        invoice_number=number,
        amount=amount,
        tax=0.0,
        total=round(amount, 2),
        status=status,
        due_date=due,
        notes=notes.strip() or None,
    )
    session.add(invoice)
    session.commit()
    logger.info("Facture créée : %s par %s", number, user.username)
    return RedirectResponse("/invoices", status_code=303)


# ── Changer statut ────────────────────────────────────────────────────────────

@router.post("/invoice/{invoice_id}/status")
def update_invoice_status(
    invoice_id: int,
    request: Request,
    status: str = Form(...),
    payment_method: str = Form(""),
    session: Session = Depends(get_session),
):
    user, redirect = get_user_or_redirect(request, session)
    if redirect:
        return redirect
    invoice = session.scalars(select(Invoice).where(Invoice.id == invoice_id)).first()
    if not invoice:
        raise HTTPException(status_code=404, detail="Facture introuvable")
    invoice.status = status
    if status == "paid":
        invoice.paid_at = datetime.now(timezone.utc)
        invoice.payment_method = payment_method or "cash"
    session.commit()
    logger.info("Facture %s → statut %s par %s", invoice.invoice_number, status, user.username)
    return RedirectResponse("/invoices", status_code=303)


# ── Supprimer facture ─────────────────────────────────────────────────────────

@router.post("/delete/invoice/{invoice_id}")
def delete_invoice(invoice_id: int, request: Request, session: Session = Depends(get_session)):
    user, redirect = get_admin_or_redirect(request, session)
    if redirect:
        return redirect
    invoice = session.scalars(select(Invoice).where(Invoice.id == invoice_id)).first()
    if invoice:
        logger.info("Facture supprimée : %s par %s", invoice.invoice_number, user.username)
        session.delete(invoice)
        session.commit()
    return RedirectResponse("/invoices", status_code=303)

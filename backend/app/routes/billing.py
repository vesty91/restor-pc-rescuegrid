"""
routes/billing.py — Restor-PC RescueGrid v12.5.2
------------------------------------------------
Factures : GET/POST /invoices, actions statut et suppression.

NOTE : /quotes et actions email/paiement liées sont dans routes/quotes.py.
       Ce fichier gère la liste/création des factures et l'export comptable.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from io import BytesIO

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from openpyxl import Workbook
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import stripe_payments
from ..database import get_session
from ..deps import get_user_or_redirect
from ..auth import get_admin_or_redirect
from ..helpers import _company_info, allocate_document_number, paginate_query, to_money
from ..models import Intervention, Invoice
from ..services.billing_defaults import SERVICE_TEMPLATES, template_by_id

logger = logging.getLogger(__name__)
router = APIRouter()
_templates: Jinja2Templates | None = None
_default_billing_amount = None


def init_router(templates, next_doc_fn, billing_fn) -> APIRouter:
    # next_doc_fn conservé pour compatibilité d'appel depuis main.py (non utilisé
    # ici : on importe allocate_document_number directement).
    global _templates, _default_billing_amount
    _templates = templates
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
        "stripe_enabled": stripe_payments.stripe_enabled(),
        "service_templates": SERVICE_TEMPLATES,
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
    service_template: str = Form(""),
    send_email: str = Form(""),
    session: Session = Depends(get_session),
):
    user, redirect = get_user_or_redirect(request, session)
    if redirect:
        return redirect
    intervention = session.get(Intervention, intervention_id)
    if not intervention:
        # Évite une IntegrityError 500 (contrainte de clé étrangère, notamment
        # sous PostgreSQL) si intervention_id ne correspond à aucune ligne —
        # cas possible avec un formulaire manipulé ou une intervention supprimée
        # entre le chargement du formulaire et la soumission.
        raise HTTPException(status_code=400, detail="Intervention introuvable pour cette facture")
    tpl = template_by_id(service_template) if service_template else None
    if tpl:
        if not notes or not notes.strip():
            notes = str(tpl["description"])
        if not amount or float(amount) <= 0:
            amount = float(tpl["amount"])
    money = to_money(amount)
    due = None
    if due_date:
        try:
            due = datetime.strptime(due_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        except ValueError:
            pass

    def build_row(number: str) -> Invoice:
        return Invoice(
            intervention_id=intervention_id,
            client_id=intervention.client_id if intervention else None,
            invoice_number=number,
            amount=money,
            tax=to_money(0),
            total=money,
            status=status,
            due_date=due,
            notes=notes.strip() or None,
        )

    invoice = allocate_document_number(session, "INV", Invoice, "invoice_number", build_row)
    logger.info("Facture créée : %s par %s", invoice.invoice_number, user.username)
    want_mail = str(send_email or "").strip().lower() in {"1", "true", "yes", "on", "o", "oui"}
    if want_mail:
        return RedirectResponse(f"/invoice/{invoice.id}/send-email", status_code=303)
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


# ── Comptabilité auto-entrepreneur (registre des recettes) ────────────────────
# Régime micro-entrepreneur : la comptabilité se fait sur encaissements (recettes
# effectivement perçues), pas sur facturation. On exporte donc les factures dont
# le statut est "paid" et dont la date d'encaissement (paid_at) tombe dans la
# période demandée — cela correspond au livre de recettes exigé par la loi.

def _period_bounds(from_str: str, to_str: str) -> tuple[datetime, datetime, str, str]:
    """Normalise les bornes de période, par défaut le mois civil en cours."""
    now = datetime.now(timezone.utc)
    default_from = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    default_to = now
    try:
        period_from = datetime.strptime(from_str, "%Y-%m-%d").replace(tzinfo=timezone.utc) if from_str else default_from
    except ValueError:
        period_from = default_from
    try:
        period_to = (datetime.strptime(to_str, "%Y-%m-%d") + timedelta(days=1) - timedelta(seconds=1)).replace(tzinfo=timezone.utc) if to_str else default_to
    except ValueError:
        period_to = default_to
    return period_from, period_to, period_from.strftime("%Y-%m-%d"), period_to.strftime("%Y-%m-%d")


def _paid_invoices_in_period(session: Session, period_from: datetime, period_to: datetime) -> list[Invoice]:
    return session.scalars(
        select(Invoice)
        .where(Invoice.status == "paid")
        .where(Invoice.paid_at.is_not(None))
        .where(Invoice.paid_at >= period_from)
        .where(Invoice.paid_at <= period_to)
        .order_by(Invoice.paid_at.asc())
    ).all()


@router.get("/comptabilite", response_class=HTMLResponse)
def comptabilite_page(
    request: Request,
    date_from: str = "",
    date_to: str = "",
    session: Session = Depends(get_session),
):
    user, redirect = get_admin_or_redirect(request, session)
    if redirect:
        return redirect
    period_from, period_to, from_label, to_label = _period_bounds(date_from, date_to)
    invoices = _paid_invoices_in_period(session, period_from, period_to)
    total = sum(float(i.total or 0) for i in invoices)
    return _templates.TemplateResponse("comptabilite.html", {
        "request": request,
        "user": user,
        "active_page": "comptabilite",
        "invoices": invoices,
        "total": total,
        "date_from": from_label,
        "date_to": to_label,
        "company": _company_info(),
    })


@router.get("/export/comptable.xlsx")
def export_comptable_xlsx(
    request: Request,
    date_from: str = "",
    date_to: str = "",
    session: Session = Depends(get_session),
):
    user, redirect = get_admin_or_redirect(request, session)
    if redirect:
        return redirect
    period_from, period_to, from_label, to_label = _period_bounds(date_from, date_to)
    invoices = _paid_invoices_in_period(session, period_from, period_to)
    company = _company_info()

    wb = Workbook()
    ws = wb.active
    ws.title = "Registre des recettes"
    ws.append([company["name"], "", "", ""])
    ws.append([company["siret"], "", "", ""])
    ws.append([f"Registre des recettes du {from_label} au {to_label}", "", "", ""])
    ws.append([])
    ws.append(["Date encaissement", "N° facture", "Client", "Montant (€)", "Mode de paiement"])
    for inv in invoices:
        ws.append([
            inv.paid_at.strftime("%d/%m/%Y") if inv.paid_at else "",
            inv.invoice_number,
            inv.client.name if inv.client else "",
            round(float(inv.total or 0), 2),
            inv.payment_method or "",
        ])
    total = sum(float(i.total or 0) for i in invoices)
    ws.append([])
    ws.append(["", "", "TOTAL PÉRIODE", round(total, 2), ""])

    buf = BytesIO()
    wb.save(buf)
    buf.seek(0)
    filename = f"registre-recettes_{from_label}_{to_label}.xlsx"
    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )

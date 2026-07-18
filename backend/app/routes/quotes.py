"""Routes devis / actions factures liées (email, paiement, conversion)."""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import stripe_payments
from ..auth import get_admin_or_redirect, get_user_or_redirect, log_activity
from ..database import get_session
from ..helpers import allocate_document_number, invoice_html, paginate_query, quote_html, to_money, try_pdf_response
from ..models import Invoice, Intervention, Quote
from ..services.billing_defaults import (
    SERVICE_TEMPLATES,
    default_billing_amount,
    default_due_date,
    default_service_description,
    template_by_id,
)
from ..services.mail import send_document_email

router = APIRouter()
_templates: Jinja2Templates | None = None


def init_router(templates: Jinja2Templates) -> APIRouter:
    global _templates
    _templates = templates
    return router


def _smtp_not_configured_redirect(kind: str) -> RedirectResponse:
    target = "/quotes" if kind == "quote" else "/invoices"
    return RedirectResponse(f"{target}?mail=smtp_not_configured", status_code=303)


@router.get("/devis")
def devis_alias():
    return RedirectResponse("/quotes", status_code=303)


@router.get("/factures")
def factures_alias():
    return RedirectResponse("/invoices", status_code=303)


@router.get("/devis/{quote_id}")
def devis_detail_alias(quote_id: int):
    return RedirectResponse(f"/quote/{quote_id}/pdf", status_code=303)


@router.get("/facture/{invoice_id}")
def facture_detail_alias(invoice_id: int):
    return RedirectResponse(f"/invoice/{invoice_id}/pdf", status_code=303)


@router.get("/quotes", response_class=HTMLResponse)
def quotes_list(request: Request, page: int = 1, session: Session = Depends(get_session)):
    user, redirect = get_user_or_redirect(request, session)
    if redirect:
        return redirect
    query = select(Quote).order_by(Quote.created_at.desc())
    quotes, page, total_pages, total_items = paginate_query(session, query, page)
    interventions = session.scalars(select(Intervention).order_by(Intervention.created_at.desc())).all()
    return _templates.TemplateResponse("quotes.html", {
        "active_page": "quotes",
        "request": request,
        "quotes": quotes,
        "interventions": interventions,
        "user": user,
        "default_billing_amount": default_billing_amount,
        "default_due_date": default_due_date,
        "service_templates": SERVICE_TEMPLATES,
        "page": page,
        "total_pages": total_pages,
        "total_items": total_items,
    })


@router.post("/quotes")
def create_quote(
    request: Request,
    intervention_id: int = Form(...),
    amount: float = Form(0.0),
    description: str = Form(""),
    status: str = Form("draft"),
    valid_until: str = Form(""),
    service_template: str = Form(""),
    send_email: str = Form(""),
    session: Session = Depends(get_session),
):
    user, redirect = get_user_or_redirect(request, session)
    if redirect:
        return redirect
    intervention = session.scalars(select(Intervention).where(Intervention.id == intervention_id)).first()
    if not intervention:
        raise HTTPException(status_code=404, detail="Intervention introuvable")
    tpl = template_by_id(service_template) if service_template else None
    if tpl:
        if not description or not description.strip():
            description = str(tpl["description"])
        if not amount or amount <= 0:
            amount = float(tpl["amount"])
    if not amount or amount <= 0:
        amount = default_billing_amount(intervention)
    money = to_money(amount)
    clean_description = (
        description.strip()
        if description and description.strip()
        else default_service_description(intervention)
    )
    valid = datetime.strptime(valid_until, "%Y-%m-%d") if valid_until else None

    def build_row(quote_number: str) -> Quote:
        return Quote(
            intervention_id=intervention_id,
            client_id=intervention.client_id,
            quote_number=quote_number,
            description=clean_description,
            amount=money,
            tax=to_money(0),
            total=money,
            status=status,
            valid_until=valid,
        )

    quote = allocate_document_number(session, "DEV", Quote, "quote_number", build_row)
    log_activity(session, user, "quote.create", quote.quote_number)
    session.commit()

    want_mail = str(send_email or "").strip().lower() in {"1", "true", "yes", "on", "o", "oui"}
    if want_mail:
        return RedirectResponse(f"/quote/{quote.id}/send-email", status_code=303)
    return RedirectResponse("/quotes", status_code=303)


@router.post("/delete/quote/{quote_id}")
def delete_quote(quote_id: int, request: Request, session: Session = Depends(get_session)):
    user, redirect = get_admin_or_redirect(request, session)
    if redirect:
        return redirect
    quote = session.scalars(select(Quote).where(Quote.id == quote_id)).first()
    if quote:
        session.delete(quote)
        log_activity(session, user, "quote.delete", str(quote_id))
        session.commit()
    return RedirectResponse("/quotes", status_code=303)


@router.get("/quote/{quote_id}/pdf")
def quote_pdf(quote_id: int, request: Request, session: Session = Depends(get_session)):
    user, redirect = get_user_or_redirect(request, session)
    if redirect:
        return redirect
    quote = session.scalars(select(Quote).where(Quote.id == quote_id)).first()
    if not quote:
        raise HTTPException(status_code=404, detail="Devis introuvable")
    return try_pdf_response(quote_html(quote), f"{quote.quote_number}.pdf")


@router.post("/quote/{quote_id}/send-email")
def send_quote_email(quote_id: int, request: Request, session: Session = Depends(get_session)):
    user, redirect = get_user_or_redirect(request, session)
    if redirect:
        return redirect
    quote_obj = session.scalars(select(Quote).where(Quote.id == quote_id)).first()
    if not quote_obj:
        raise HTTPException(status_code=404, detail="Devis introuvable")
    client = quote_obj.client
    if not client or not client.email:
        target = (
            f"/client/{client.id}?mail=missing_client_email&next=quotes"
            if client
            else "/quotes?mail=missing_client_email"
        )
        return RedirectResponse(target, status_code=303)
    subject = f"Devis Restor-PC {quote_obj.quote_number}"
    body = (
        f"Bonjour {client.name},\n\n"
        f"Veuillez trouver votre devis Restor-PC {quote_obj.quote_number}.\n"
        f"Montant : {quote_obj.amount:.2f} €.\n\n"
        "Cordialement,\nRESTOR-PC\ncontact@restor-pc.fr"
    )
    ok, detail = send_document_email(
        to_email=client.email,
        subject=subject,
        body=body,
        html_attachment=quote_html(quote_obj),
        attachment_name=f"{quote_obj.quote_number}.pdf",
    )
    if ok:
        quote_obj.status = "sent"
        log_activity(session, user, "quote.email", quote_obj.quote_number)
        session.commit()
        return RedirectResponse("/quotes?mail=sent", status_code=303)
    if detail == "smtp_not_configured":
        return _smtp_not_configured_redirect("quote")
    log_activity(session, user, "quote.email_error", f"{quote_obj.quote_number} {detail}")
    session.commit()
    return RedirectResponse("/quotes?mail=error", status_code=303)


@router.post("/invoice/{invoice_id}/send-email")
def send_invoice_email(invoice_id: int, request: Request, session: Session = Depends(get_session)):
    user, redirect = get_user_or_redirect(request, session)
    if redirect:
        return redirect
    invoice_obj = session.scalars(select(Invoice).where(Invoice.id == invoice_id)).first()
    if not invoice_obj:
        raise HTTPException(status_code=404, detail="Facture introuvable")
    client = invoice_obj.client
    if not client or not client.email:
        target = (
            f"/client/{client.id}?mail=missing_client_email&next=invoices"
            if client
            else "/invoices?mail=missing_client_email"
        )
        return RedirectResponse(target, status_code=303)
    payment_link = stripe_payments.ensure_payment_link(session, invoice_obj)
    payment_line = f"\nPayer en ligne par carte bancaire : {payment_link}\n" if payment_link else ""
    subject = f"Facture Restor-PC {invoice_obj.invoice_number}"
    body = (
        f"Bonjour {client.name},\n\n"
        f"Veuillez trouver votre facture Restor-PC {invoice_obj.invoice_number}.\n"
        f"Montant : {invoice_obj.amount:.2f} €.\n"
        f"{payment_line}\n"
        "Cordialement,\nRESTOR-PC\ncontact@restor-pc.fr"
    )
    ok, detail = send_document_email(
        to_email=client.email,
        subject=subject,
        body=body,
        html_attachment=invoice_html(invoice_obj),
        attachment_name=f"{invoice_obj.invoice_number}.pdf",
    )
    if ok:
        invoice_obj.status = "issued" if invoice_obj.status == "draft" else invoice_obj.status
        log_activity(session, user, "invoice.email", invoice_obj.invoice_number)
        session.commit()
        return RedirectResponse("/invoices?mail=sent", status_code=303)
    if detail == "smtp_not_configured":
        return _smtp_not_configured_redirect("invoice")
    log_activity(session, user, "invoice.email_error", f"{invoice_obj.invoice_number} {detail}")
    session.commit()
    return RedirectResponse("/invoices?mail=error", status_code=303)


@router.post("/quote/{quote_id}/convert")
def convert_quote_to_invoice(quote_id: int, request: Request, session: Session = Depends(get_session)):
    user, redirect = get_user_or_redirect(request, session)
    if redirect:
        return redirect
    quote = session.scalars(select(Quote).where(Quote.id == quote_id)).first()
    if not quote:
        raise HTTPException(status_code=404, detail="Devis introuvable")
    existing = session.scalars(select(Invoice).where(Invoice.quote_id == quote_id)).first()
    if existing:
        return RedirectResponse(f"/invoice/{existing.id}/pdf", status_code=303)
    money = to_money(quote.amount)
    notes = quote.description or default_service_description(quote.intervention)

    def build_row(invoice_number: str) -> Invoice:
        return Invoice(
            intervention_id=quote.intervention_id,
            client_id=quote.client_id,
            quote_id=quote.id,
            invoice_number=invoice_number,
            amount=money,
            tax=to_money(0),
            total=money,
            status="draft",
            notes=notes,
        )

    invoice = allocate_document_number(session, "INV", Invoice, "invoice_number", build_row)
    quote.status = "accepted"
    log_activity(session, user, "quote.convert", f"{quote.quote_number} -> {invoice.invoice_number}")
    session.commit()
    return RedirectResponse("/invoices", status_code=303)


@router.post("/invoice/{invoice_id}/pay")
def mark_invoice_paid(
    invoice_id: int,
    request: Request,
    payment_method: str = Form("cash"),
    session: Session = Depends(get_session),
):
    user, redirect = get_user_or_redirect(request, session)
    if redirect:
        return redirect
    invoice = session.scalars(select(Invoice).where(Invoice.id == invoice_id)).first()
    if not invoice:
        raise HTTPException(status_code=404, detail="Facture introuvable")
    invoice.status = "paid"
    invoice.paid_at = datetime.now(timezone.utc)
    invoice.payment_method = payment_method
    log_activity(session, user, "invoice.pay", invoice.invoice_number)
    session.commit()
    return RedirectResponse("/invoices", status_code=303)

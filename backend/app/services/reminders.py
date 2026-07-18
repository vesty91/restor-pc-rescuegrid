"""Relances devis/factures (bouton manuel + scheduler)."""
from __future__ import annotations

from sqlalchemy.orm import Session

from .. import stripe_payments
from ..auth import log_activity
from ..helpers import invoice_html, quote_html
from ..models import Invoice, Quote, Reminder, User
from .mail import send_document_email


def send_quote_reminder(session: Session, quote: Quote, user: User | None = None) -> tuple[bool, str]:
    client = quote.client
    if not client or not client.email:
        return False, "missing_client_email"
    subject = f"Rappel — Devis Restor-PC {quote.quote_number} en attente de réponse"
    body = (
        f"Bonjour {client.name},\n\n"
        f"Nous restons à votre disposition concernant le devis {quote.quote_number} "
        f"({quote.amount:.2f} €), toujours en attente de votre réponse.\n\n"
        "Cordialement,\nRESTOR-PC\ncontact@restor-pc.fr"
    )
    ok, detail = send_document_email(
        to_email=client.email,
        subject=subject,
        body=body,
        html_attachment=quote_html(quote),
        attachment_name=f"{quote.quote_number}.pdf",
    )
    origin = "auto" if user is None else "manuel"
    if ok:
        session.add(Reminder(target_type="quote", target_id=quote.id, sent_by_user_id=user.id if user else None))
        log_activity(session, user, "quote.remind", f"{quote.quote_number} ({origin})")
        session.commit()
        return True, "sent"
    log_activity(session, user, "quote.remind_error", f"{quote.quote_number} {detail} ({origin})")
    session.commit()
    return False, detail


def send_invoice_reminder(session: Session, invoice: Invoice, user: User | None = None) -> tuple[bool, str]:
    client = invoice.client
    if not client or not client.email:
        return False, "missing_client_email"
    payment_link = stripe_payments.ensure_payment_link(session, invoice)
    payment_line = f"\nPayer en ligne par carte bancaire : {payment_link}\n" if payment_link else ""
    subject = f"Rappel — Facture Restor-PC {invoice.invoice_number} en attente de paiement"
    body = (
        f"Bonjour {client.name},\n\n"
        f"Nous vous rappelons que la facture {invoice.invoice_number} "
        f"({invoice.amount:.2f} €) est toujours en attente de règlement.\n"
        f"{payment_line}\n"
        "Cordialement,\nRESTOR-PC\ncontact@restor-pc.fr"
    )
    ok, detail = send_document_email(
        to_email=client.email,
        subject=subject,
        body=body,
        html_attachment=invoice_html(invoice),
        attachment_name=f"{invoice.invoice_number}.pdf",
    )
    origin = "auto" if user is None else "manuel"
    if ok:
        session.add(Reminder(target_type="invoice", target_id=invoice.id, sent_by_user_id=user.id if user else None))
        log_activity(session, user, "invoice.remind", f"{invoice.invoice_number} ({origin})")
        session.commit()
        return True, "sent"
    log_activity(session, user, "invoice.remind_error", f"{invoice.invoice_number} {detail} ({origin})")
    session.commit()
    return False, detail

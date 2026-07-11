"""Routes v12 Stable — devis, factures, SMTP direct, intervention detail, settings, users."""
from __future__ import annotations

import base64
import csv
import logging
import io
import re
import shutil
import os
import smtplib
from email.message import EmailMessage
from email.utils import formataddr
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

# Chargement robuste des fichiers .env.
# Priorité : backend/.env puis .env racine projet si présent.
_BACKEND_DIR = Path(__file__).resolve().parents[1]
_PROJECT_DIR = _BACKEND_DIR.parent
load_dotenv(_PROJECT_DIR / ".env", override=False)
load_dotenv(_BACKEND_DIR / ".env", override=True)


from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import Session

from .auth import get_admin_or_redirect, get_user_or_redirect, hash_password, log_activity, validate_password_strength
from .database import get_session
from .helpers import generate_ai_summary, quote_html, invoice_html, paginate_query, render_document_pdf, try_pdf_response
from .models import ActivityLog, Client, Intervention, InterventionPart, InterventionPhoto, Invoice, Part, Quote, Reminder, Ticket, User

logger = logging.getLogger(__name__)

router = APIRouter()


def _smtp_config() -> dict:
    """Configuration SMTP unifiée, compatible Infomaniak et anciens noms SMTP_*.

    Fonction module-level (pas dans la closure de init_v10_routes) afin d'être
    réutilisable par d'autres modules (ex: routes/client_portal.py pour l'email
    d'activation de l'espace client) sans dépendre de l'initialisation des routes.
    """
    return {
        "enabled": (os.getenv("MAIL_ENABLED") or "true").lower() in {"1", "true", "yes", "on"},
        "host": os.getenv("SMTP_HOST") or os.getenv("MAIL_SERVER") or "mail.infomaniak.com",
        "port": int(os.getenv("SMTP_PORT") or os.getenv("MAIL_PORT") or "587"),
        "user": os.getenv("SMTP_USER") or os.getenv("MAIL_USERNAME") or "contact@restor-pc.fr",
        "password": os.getenv("SMTP_PASSWORD") or os.getenv("MAIL_PASSWORD") or "",
        "sender": os.getenv("SMTP_SENDER") or os.getenv("MAIL_DEFAULT_SENDER") or os.getenv("MAIL_USERNAME") or "contact@restor-pc.fr",
        "from_name": os.getenv("MAIL_FROM_NAME") or "RESTOR-PC",
        "use_ssl": (os.getenv("SMTP_SSL") or os.getenv("MAIL_USE_SSL") or "").lower() in {"1", "true", "yes", "on"},
        "use_tls": (os.getenv("SMTP_TLS") or os.getenv("MAIL_USE_TLS") or "true").lower() in {"1", "true", "yes", "on"},
    }


def send_document_email(
    *,
    to_email: str,
    subject: str,
    body: str,
    html_attachment: str,
    attachment_name: str,
) -> tuple[bool, str]:
    """Envoi SMTP Infomaniak. Attache un PDF si wkhtmltopdf est installé, sinon un HTML imprimable.

    Fonction module-level partagée (routes_v10.py et routes/client_portal.py).
    """
    cfg = _smtp_config()
    if not cfg["enabled"] or not cfg["password"]:
        return False, "smtp_not_configured"

    payload, maintype, subtype, final_name = render_document_pdf(html_attachment, attachment_name)

    msg = EmailMessage()
    msg["From"] = formataddr((cfg["from_name"], cfg["sender"]))
    msg["To"] = to_email
    msg["Subject"] = subject
    msg["Reply-To"] = cfg["sender"]
    msg.set_content(body)
    msg.add_attachment(payload, maintype=maintype, subtype=subtype, filename=final_name)

    try:
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
        return True, "sent_pdf" if subtype == "pdf" else "sent_html_fallback"
    except Exception as exc:
        return False, f"smtp_error:{exc}"


def init_v10_routes(templates: Jinja2Templates, storage_dir: Path, report_dir: Path, sanitize_filename, intervention_dir_fn, resolve_storage_path):
    """Injecte les dépendances depuis main."""

    PHOTOS_DIR = storage_dir / "photos"
    SIGNATURES_DIR = storage_dir / "signatures"
    PHOTOS_DIR.mkdir(parents=True, exist_ok=True)
    SIGNATURES_DIR.mkdir(parents=True, exist_ok=True)

    def _default_service_description(intervention: Intervention | None) -> str:
        if not intervention:
            return "Diagnostic atelier, contrôle système et rapport Restor-PC."
        score = f" Score santé {intervention.health_score}/100." if intervention.health_score is not None else ""
        return (
            "Diagnostic atelier, contrôle SMART, analyse Windows et rapport d'intervention Restor-PC."
            + score
        )

    def _default_billing_amount(intervention: Intervention | None) -> float:
        """Taux atelier Restor-PC : 60 €/h.
        Si une main-d'œuvre est saisie sur l'intervention, le montant est calculé automatiquement.
        Sinon on préremplit une intervention forfaitaire à 60 €.
        """
        if not intervention:
            return 60.0
        minutes = int(getattr(intervention, "labor_minutes", 0) or 0)
        rate = float(getattr(intervention, "labor_rate", 0) or 60.0)
        if minutes > 0:
            return round((minutes / 60.0) * rate, 2)
        return 60.0

    def _default_due_date(days: int = 30) -> str:
        from datetime import timedelta
        return (datetime.now(timezone.utc) + timedelta(days=days)).strftime("%Y-%m-%d")


    def _next_document_number(session: Session, prefix: str, model, field_name: str) -> str:
        """Genere un numero unique journalier: DEV-YYYYMMDD-0001 / INV-YYYYMMDD-0001."""
        today = datetime.now(timezone.utc).strftime("%Y%m%d")
        pattern = f"{prefix}-{today}-%"
        field = getattr(model, field_name)
        existing_numbers = session.scalars(select(field).where(field.like(pattern))).all()
        max_index = 0
        for number in existing_numbers:
            match = re.match(rf"^{prefix}-{today}-(\d{{4,}})$", str(number or ""))
            if match:
                max_index = max(max_index, int(match.group(1)))
        return f"{prefix}-{today}-{max_index + 1:04d}"


    # Alias FR pour l'interface atelier
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
        return templates.TemplateResponse("quotes.html", {"active_page": "quotes", 
            "request": request, "quotes": quotes, "interventions": interventions, "user": user,
            "default_billing_amount": _default_billing_amount, "default_due_date": _default_due_date,
            "page": page, "total_pages": total_pages, "total_items": total_items,
        })

    @router.post("/quotes")
    def create_quote(
        request: Request,
        intervention_id: int = Form(...),
        amount: float = Form(0.0),
        description: str = Form(""),
        status: str = Form("draft"),
        valid_until: str = Form(""),
        session: Session = Depends(get_session),
    ):
        user, redirect = get_user_or_redirect(request, session)
        if redirect:
            return redirect
        intervention = session.scalars(select(Intervention).where(Intervention.id == intervention_id)).first()
        if not intervention:
            raise HTTPException(status_code=404, detail="Intervention introuvable")
        if not amount or amount <= 0:
            amount = _default_billing_amount(intervention)
        tax = 0.0
        total = amount
        quote_number = _next_document_number(session, "DEV", Quote, "quote_number")
        clean_description = description.strip() if description and description.strip() else _default_service_description(intervention)
        quote = Quote(
            intervention_id=intervention_id,
            client_id=intervention.client_id,
            quote_number=quote_number,
            description=clean_description,
            amount=amount,
            tax=tax,
            total=total,
            status=status,
            valid_until=datetime.strptime(valid_until, "%Y-%m-%d") if valid_until else None,
        )
        session.add(quote)
        log_activity(session, user, "quote.create", quote_number)
        session.commit()
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


    # Alias local : le reste du fichier utilise _send_document_email, désormais
    # une fonction module-level (send_document_email) partagée avec client_portal.py.
    _send_document_email = send_document_email

    def _smtp_not_configured_redirect(kind: str) -> RedirectResponse:
        target = "/quotes" if kind == "quote" else "/invoices"
        return RedirectResponse(f"{target}?mail=smtp_not_configured", status_code=303)

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
            target = f"/client/{client.id}?mail=missing_client_email&next=quotes" if client else "/quotes?mail=missing_client_email"
            return RedirectResponse(target, status_code=303)
        subject = f"Devis Restor-PC {quote_obj.quote_number}"
        body = (
            f"Bonjour {client.name},\n\n"
            f"Veuillez trouver votre devis Restor-PC {quote_obj.quote_number}.\n"
            f"Montant : {quote_obj.amount:.2f} €.\n\n"
            "Cordialement,\nRESTOR-PC\ncontact@restor-pc.fr"
        )
        html_doc = quote_html(quote_obj)
        ok, detail = _send_document_email(
            to_email=client.email,
            subject=subject,
            body=body,
            html_attachment=html_doc,
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
            target = f"/client/{client.id}?mail=missing_client_email&next=invoices" if client else "/invoices?mail=missing_client_email"
            return RedirectResponse(target, status_code=303)
        subject = f"Facture Restor-PC {invoice_obj.invoice_number}"
        body = (
            f"Bonjour {client.name},\n\n"
            f"Veuillez trouver votre facture Restor-PC {invoice_obj.invoice_number}.\n"
            f"Montant : {invoice_obj.amount:.2f} €.\n\n"
            "Cordialement,\nRESTOR-PC\ncontact@restor-pc.fr"
        )
        html_doc = invoice_html(invoice_obj)
        ok, detail = _send_document_email(
            to_email=client.email,
            subject=subject,
            body=body,
            html_attachment=html_doc,
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


    # ── Relances devis/factures en retard (semi-automatique) ───────────────
    # Pas de scheduler : le technicien consulte /relances et déclenche l'envoi
    # au clic. Chaque envoi est tracé dans Reminder pour éviter les doublons
    # et afficher la date de dernière relance sur la liste.

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
            select(Quote).where(Quote.status == "sent", Quote.valid_until.is_not(None), Quote.valid_until < now)
            .order_by(Quote.valid_until.asc())
        ).all()
        overdue_invoices = session.scalars(
            select(Invoice).where(Invoice.status == "issued", Invoice.due_date.is_not(None), Invoice.due_date < now)
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
        return templates.TemplateResponse("relances.html", {"active_page": "relances",
            "request": request, "user": user,
            "quote_rows": quote_rows, "invoice_rows": invoice_rows,
        })

    @router.post("/quote/{quote_id}/remind")
    def remind_quote(quote_id: int, request: Request, session: Session = Depends(get_session)):
        user, redirect = get_user_or_redirect(request, session)
        if redirect:
            return redirect
        quote_obj = session.scalars(select(Quote).where(Quote.id == quote_id)).first()
        if not quote_obj:
            raise HTTPException(status_code=404, detail="Devis introuvable")
        client = quote_obj.client
        if not client or not client.email:
            return RedirectResponse("/relances?mail=missing_client_email", status_code=303)
        subject = f"Rappel — Devis Restor-PC {quote_obj.quote_number} en attente de réponse"
        body = (
            f"Bonjour {client.name},\n\n"
            f"Nous restons à votre disposition concernant le devis {quote_obj.quote_number} "
            f"({quote_obj.amount:.2f} €), toujours en attente de votre réponse.\n\n"
            "Cordialement,\nRESTOR-PC\ncontact@restor-pc.fr"
        )
        ok, detail = _send_document_email(
            to_email=client.email, subject=subject, body=body,
            html_attachment=quote_html(quote_obj), attachment_name=f"{quote_obj.quote_number}.pdf",
        )
        if ok:
            session.add(Reminder(target_type="quote", target_id=quote_id, sent_by_user_id=user.id))
            log_activity(session, user, "quote.remind", quote_obj.quote_number)
            session.commit()
            return RedirectResponse("/relances?mail=sent", status_code=303)
        log_activity(session, user, "quote.remind_error", f"{quote_obj.quote_number} {detail}")
        session.commit()
        return RedirectResponse("/relances?mail=error", status_code=303)

    @router.post("/invoice/{invoice_id}/remind")
    def remind_invoice(invoice_id: int, request: Request, session: Session = Depends(get_session)):
        user, redirect = get_user_or_redirect(request, session)
        if redirect:
            return redirect
        invoice_obj = session.scalars(select(Invoice).where(Invoice.id == invoice_id)).first()
        if not invoice_obj:
            raise HTTPException(status_code=404, detail="Facture introuvable")
        client = invoice_obj.client
        if not client or not client.email:
            return RedirectResponse("/relances?mail=missing_client_email", status_code=303)
        subject = f"Rappel — Facture Restor-PC {invoice_obj.invoice_number} en attente de paiement"
        body = (
            f"Bonjour {client.name},\n\n"
            f"Nous vous rappelons que la facture {invoice_obj.invoice_number} "
            f"({invoice_obj.amount:.2f} €) est toujours en attente de règlement.\n\n"
            "Cordialement,\nRESTOR-PC\ncontact@restor-pc.fr"
        )
        ok, detail = _send_document_email(
            to_email=client.email, subject=subject, body=body,
            html_attachment=invoice_html(invoice_obj), attachment_name=f"{invoice_obj.invoice_number}.pdf",
        )
        if ok:
            session.add(Reminder(target_type="invoice", target_id=invoice_id, sent_by_user_id=user.id))
            log_activity(session, user, "invoice.remind", invoice_obj.invoice_number)
            session.commit()
            return RedirectResponse("/relances?mail=sent", status_code=303)
        log_activity(session, user, "invoice.remind_error", f"{invoice_obj.invoice_number} {detail}")
        session.commit()
        return RedirectResponse("/relances?mail=error", status_code=303)

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
        invoice_number = _next_document_number(session, "INV", Invoice, "invoice_number")
        invoice = Invoice(
            intervention_id=quote.intervention_id,
            client_id=quote.client_id,
            quote_id=quote.id,
            invoice_number=invoice_number,
            amount=quote.amount,
            tax=0.0,
            total=quote.amount,
            status="draft",
            notes=quote.description or _default_service_description(quote.intervention),
        )
        quote.status = "accepted"
        session.add(invoice)
        log_activity(session, user, "quote.convert", f"{quote.quote_number} -> {invoice_number}")
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

    @router.get("/intervention/{intervention_id}", response_class=HTMLResponse)
    def intervention_detail(intervention_id: int, request: Request, session: Session = Depends(get_session)):
        user, redirect = get_user_or_redirect(request, session)
        if redirect:
            return redirect
        intervention = session.scalars(select(Intervention).where(Intervention.id == intervention_id)).first()
        if not intervention:
            raise HTTPException(status_code=404, detail="Intervention introuvable")
        parts = session.scalars(select(Part).order_by(Part.part_type)).all()
        tickets = session.scalars(select(Ticket).where(Ticket.intervention_id == intervention_id)).all()
        quotes = session.scalars(select(Quote).where(Quote.intervention_id == intervention_id).order_by(Quote.created_at.desc())).all()
        invoices = session.scalars(select(Invoice).where(Invoice.intervention_id == intervention_id).order_by(Invoice.created_at.desc())).all()
        folder = intervention_dir_fn(intervention)
        if folder and not intervention.ai_summary:
            intervention.ai_summary = generate_ai_summary(intervention, folder)
            session.commit()
        return templates.TemplateResponse("intervention_detail.html", {"active_page": "interventions", 
            "request": request,
            "intervention": intervention,
            "parts": parts,
            "tickets": tickets,
            "quotes": quotes,
            "invoices": invoices,
            "user": user,
            "atelier_statuses": ["nouvelle", "en_attente", "en_cours", "termine", "livre", "facture"],
            "default_amount": _default_billing_amount(intervention),
            "default_quote_until": _default_due_date(30),
            "default_invoice_due": _default_due_date(0),
        })

    @router.post("/intervention/{intervention_id}/photo")
    async def upload_intervention_photo(
        intervention_id: int,
        request: Request,
        phase: str = Form("during"),
        file: UploadFile = File(...),
        session: Session = Depends(get_session),
    ):
        user, redirect = get_user_or_redirect(request, session)
        if redirect:
            return redirect
        intervention = session.scalars(select(Intervention).where(Intervention.id == intervention_id)).first()
        if not intervention:
            raise HTTPException(status_code=404, detail="Intervention introuvable")
        if phase not in {"before", "during", "after"}:
            phase = "during"
        if not file.content_type or not file.content_type.startswith("image/"):
            raise HTTPException(status_code=400, detail="Image requise")
        safe = sanitize_filename(file.filename or "photo.jpg")
        rel = f"photos/int_{intervention_id}_{phase}_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}_{safe}"
        target = storage_dir / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        photo = InterventionPhoto(intervention_id=intervention_id, phase=phase, file_path=rel)
        session.add(photo)
        log_activity(session, user, "intervention.photo", f"#{intervention_id} {phase}")
        session.commit()
        return RedirectResponse(f"/intervention/{intervention_id}", status_code=303)

    @router.post("/intervention/{intervention_id}/signature")
    async def save_intervention_signature(
        intervention_id: int,
        request: Request,
        signature_data: str = Form(...),
        session: Session = Depends(get_session),
    ):
        user, redirect = get_user_or_redirect(request, session)
        if redirect:
            return redirect
        intervention = session.scalars(select(Intervention).where(Intervention.id == intervention_id)).first()
        if not intervention:
            raise HTTPException(status_code=404, detail="Intervention introuvable")
        match = re.match(r"data:image/(png|jpeg|jpg);base64,(.+)", signature_data, re.I)
        if not match:
            raise HTTPException(status_code=400, detail="Signature invalide")
        ext = "png" if match.group(1).lower() == "png" else "jpg"
        raw = base64.b64decode(match.group(2))
        rel = f"signatures/int_{intervention_id}_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}.{ext}"
        target = storage_dir / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
        intervention.signature_path = rel
        log_activity(session, user, "intervention.signature", f"#{intervention_id}")
        session.commit()
        return RedirectResponse(f"/intervention/{intervention_id}", status_code=303)

    @router.post("/intervention/{intervention_id}/labor")
    def update_intervention_labor(
        intervention_id: int,
        request: Request,
        labor_minutes: int = Form(0),
        labor_rate: float = Form(60.0),
        session: Session = Depends(get_session),
    ):
        user, redirect = get_user_or_redirect(request, session)
        if redirect:
            return redirect
        intervention = session.scalars(select(Intervention).where(Intervention.id == intervention_id)).first()
        if not intervention:
            raise HTTPException(status_code=404, detail="Intervention introuvable")
        intervention.labor_minutes = max(labor_minutes, 0)
        intervention.labor_rate = labor_rate if labor_rate > 0 else 60.0
        log_activity(session, user, "intervention.labor", f"#{intervention_id} {labor_minutes}min")
        session.commit()
        return RedirectResponse(f"/intervention/{intervention_id}", status_code=303)

    @router.post("/intervention/{intervention_id}/parts")
    def add_intervention_part(
        intervention_id: int,
        request: Request,
        part_id: int = Form(...),
        quantity: int = Form(1),
        notes: str = Form(""),
        session: Session = Depends(get_session),
    ):
        user, redirect = get_user_or_redirect(request, session)
        if redirect:
            return redirect
        intervention = session.scalars(select(Intervention).where(Intervention.id == intervention_id)).first()
        part = session.scalars(select(Part).where(Part.id == part_id)).first()
        if not intervention or not part:
            raise HTTPException(status_code=404, detail="Intervention ou pièce introuvable")
        qty = max(quantity, 1)
        if part.quantity < qty:
            raise HTTPException(status_code=400, detail="Stock insuffisant")
        part.quantity -= qty
        session.add(InterventionPart(
            intervention_id=intervention_id, part_id=part_id, quantity=qty, notes=notes or None,
        ))
        log_activity(session, user, "intervention.part", f"#{intervention_id} part#{part_id} x{qty}")
        session.commit()
        return RedirectResponse(f"/intervention/{intervention_id}", status_code=303)

    @router.get("/settings", response_class=HTMLResponse)
    def settings_page(request: Request, session: Session = Depends(get_session)):
        user, redirect = get_user_or_redirect(request, session)
        if redirect:
            return redirect
        return templates.TemplateResponse("settings.html", {"active_page": "settings", "request": request, "user": user, "message": None, "error": None})

    @router.post("/settings/email-test")
    def settings_email_test(
        request: Request,
        test_email: str = Form(...),
        session: Session = Depends(get_session),
    ):
        user, redirect = get_admin_or_redirect(request, session)
        if redirect:
            return redirect
        html_test = "<h1>Test email RESTOR-PC</h1><p>Configuration SMTP Infomaniak opérationnelle.</p>"
        ok, detail = _send_document_email(
            to_email=test_email.strip(),
            subject="Test email RESTOR-PC",
            body="Bonjour, ceci est un test d'envoi email depuis Restor-PC RescueGrid.",
            html_attachment=html_test,
            attachment_name="test-restor-pc.pdf",
        )
        if ok:
            log_activity(session, user, "settings.email_test", test_email.strip())
            session.commit()
            return templates.TemplateResponse("settings.html", {"active_page": "settings", 
                "request": request, "user": user,
                "message": f"Email de test envoyé à {test_email.strip()} ({detail}).",
                "error": None,
            })
        return templates.TemplateResponse("settings.html", {"active_page": "settings", 
            "request": request, "user": user,
            "message": None,
            "error": f"Erreur email : {detail}. Vérifie MAIL_PASSWORD dans .env.",
        })


    @router.post("/settings/password")
    def change_password(
        request: Request,
        current_password: str = Form(...),
        new_password: str = Form(...),
        confirm_password: str = Form(...),
        session: Session = Depends(get_session),
    ):
        from .auth import verify_password
        user, redirect = get_user_or_redirect(request, session)
        if redirect:
            return redirect
        if new_password != confirm_password:
            return templates.TemplateResponse("settings.html", {"active_page": "settings", 
                "request": request, "user": user, "message": None, "error": "Les mots de passe ne correspondent pas.",
            })
        password_error = validate_password_strength(new_password, user.username)
        if password_error:
            return templates.TemplateResponse("settings.html", {"active_page": "settings", 
                "request": request, "user": user, "message": None, "error": password_error,
            })
        if not verify_password(current_password, user.hashed_password):
            return templates.TemplateResponse("settings.html", {"active_page": "settings", 
                "request": request, "user": user, "message": None, "error": "Mot de passe actuel incorrect.",
            })
        user.hashed_password = hash_password(new_password)
        log_activity(session, user, "settings.password", user.username)
        session.commit()
        return templates.TemplateResponse("settings.html", {"active_page": "settings", 
            "request": request, "user": user, "message": "Mot de passe mis à jour.", "error": None,
        })

    @router.get("/users", response_class=HTMLResponse)
    def users_page(request: Request, session: Session = Depends(get_session)):
        user, redirect = get_admin_or_redirect(request, session)
        if redirect:
            return redirect
        users = session.scalars(select(User).order_by(User.created_at.desc())).all()
        return templates.TemplateResponse("users.html", {"active_page": "users", "request": request, "users": users, "user": user, "error": None})

    @router.post("/users")
    def create_user(
        request: Request,
        username: str = Form(...),
        password: str = Form(...),
        full_name: str = Form(""),
        role: str = Form("technicien"),
        session: Session = Depends(get_session),
    ):
        admin, redirect = get_admin_or_redirect(request, session)
        if redirect:
            return redirect
        if session.scalars(select(User).where(User.username == username)).first():
            users = session.scalars(select(User).order_by(User.created_at.desc())).all()
            return templates.TemplateResponse("users.html", {"active_page": "users", 
                "request": request, "users": users, "user": admin, "error": "Identifiant déjà utilisé.",
            })
        password_error = validate_password_strength(password, username)
        if password_error:
            users = session.scalars(select(User).order_by(User.created_at.desc())).all()
            return templates.TemplateResponse("users.html", {"active_page": "users", 
                "request": request, "users": users, "user": admin, "error": password_error,
            })
        if role not in {"admin", "technicien"}:
            role = "technicien"
        session.add(User(
            username=username.strip(),
            hashed_password=hash_password(password),
            full_name=full_name or None,
            role=role,
        ))
        log_activity(session, admin, "user.create", username)
        session.commit()
        return RedirectResponse("/users", status_code=303)

    @router.post("/delete/user/{user_id}")
    def delete_user(user_id: int, request: Request, session: Session = Depends(get_session)):
        admin, redirect = get_admin_or_redirect(request, session)
        if redirect:
            return redirect
        target = session.scalars(select(User).where(User.id == user_id)).first()
        if target and target.id != admin.id:
            session.delete(target)
            log_activity(session, admin, "user.delete", target.username)
            session.commit()
        return RedirectResponse("/users", status_code=303)

    @router.get("/activity", response_class=HTMLResponse)
    def activitylog_activity_page(request: Request, session: Session = Depends(get_session)):
        user, redirect = get_admin_or_redirect(request, session)
        if redirect:
            return redirect
        logs = session.scalars(select(ActivityLog).order_by(ActivityLog.created_at.desc()).limit(200)).all()
        return templates.TemplateResponse("activity.html", {"active_page": "activity", "request": request, "logs": logs, "user": user})

    @router.get("/export/interventions.csv")
    def export_interventions_csv(request: Request, session: Session = Depends(get_session)):
        user, redirect = get_user_or_redirect(request, session)
        if redirect:
            return redirect
        interventions = session.scalars(select(Intervention).order_by(Intervention.created_at.desc())).all()
        stream = io.StringIO()
        writer = csv.writer(stream)
        writer.writerow(["ID", "Date", "Client", "Machine", "Score", "Disque", "Statut"])
        for item in interventions:
            writer.writerow([
                item.id,
                item.created_at.strftime("%Y-%m-%d %H:%M"),
                item.client.name if item.client else "",
                item.machine_name or "",
                item.health_score or "",
                item.disk_risk or "",
                item.status,
            ])
        return StreamingResponse(
            iter([stream.getvalue().encode("utf-8-sig")]),
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=interventions.csv"},
        )

    return router

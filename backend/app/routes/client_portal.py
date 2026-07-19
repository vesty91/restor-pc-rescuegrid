"""
routes/client_portal.py — Espace client sécurisé (Restor-PC RescueGrid)
--------------------------------------------------------------------------
Authentification par mot de passe OU via Google/GitHub. Complètement séparée
de l'espace staff (voir app/client_auth.py) : cookie dédié, session propre.

  GET/POST /client/login                    → formulaire mot de passe + boutons OAuth
  GET      /client/auth/{provider}           → redirection vers le provider
  GET      /client/auth/{provider}/callback  → callback OAuth, pose du cookie
  GET      /client/logout
  GET      /client/portal                    → tableau de bord client
  GET      /client/quote/{id}/pdf            → PDF devis, scope client
  GET      /client/invoice/{id}/pdf          → PDF facture, scope client

  Côté admin (fiche client) :
  POST /client/{id}/portal/enable            → crée le ClientAccount + email d'activation
  POST /client/{id}/portal/disable           → désactive l'accès portail
  POST /client/{id}/portal/reset-password    → génère et envoie un nouveau mot de passe
"""
from __future__ import annotations

import logging
import secrets
import string
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import oauth
from ..auth import (
    COOKIE_SECURE,
    get_admin_or_redirect,
    get_user_or_redirect,
    hash_password,
    log_activity,
    validate_password_strength,
    verify_password,
)
from ..client_auth import (
    CLIENT_COOKIE_NAME,
    authenticate_client_account,
    clear_client_login_attempts,
    create_client_token,
    get_client_or_redirect,
    is_client_account_locked,
    is_client_rate_limited,
    record_client_login_failure,
)
from ..database import get_session
from ..deps import get_client_ip
from ..helpers import allocate_document_number, invoice_html, quote_html, to_money, try_pdf_response
from ..models import Appointment, Client, ClientAccount, ClientOAuthIdentity, Invoice, Intervention, Quote
from ..services.billing_defaults import default_service_description
from ..services.mail import send_document_email as _send_email_fn

logger = logging.getLogger(__name__)

router = APIRouter()
_templates: Jinja2Templates | None = None


def init_router(templates: Jinja2Templates) -> APIRouter:
    global _templates
    _templates = templates
    return router


OAUTH_STATE_COOKIE = "oauth_state"


# ── Connexion mot de passe ──────────────────────────────────────────────────

@router.get("/client/login", response_class=HTMLResponse)
def client_login_page(request: Request):
    return _templates.TemplateResponse("client/login.html", {
        "request": request, "error": None,
        "google_enabled": oauth.is_provider_configured("google"),
        "github_enabled": oauth.is_provider_configured("github"),
    })


@router.post("/client/login")
def client_login_post(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    session: Session = Depends(get_session),
):
    client_ip = get_client_ip(request)
    email_key = email.strip().lower()

    if is_client_rate_limited(client_ip):
        return _templates.TemplateResponse("client/login.html", {
            "request": request, "error": "Trop de tentatives. Réessayez dans 5 minutes.",
            "google_enabled": oauth.is_provider_configured("google"),
            "github_enabled": oauth.is_provider_configured("github"),
        }, status_code=429)

    if email_key and is_client_account_locked(email_key):
        return _templates.TemplateResponse("client/login.html", {
            "request": request, "error": "Compte temporairement verrouillé suite à plusieurs échecs. Réessayez plus tard.",
            "google_enabled": oauth.is_provider_configured("google"),
            "github_enabled": oauth.is_provider_configured("github"),
        }, status_code=429)

    account = authenticate_client_account(email, password, session)
    if not account:
        record_client_login_failure(client_ip, email_key)
        logger.warning("Échec connexion client pour %s depuis %s", email, client_ip)
        return _templates.TemplateResponse("client/login.html", {
            "request": request, "error": "Email ou mot de passe incorrect.",
            "google_enabled": oauth.is_provider_configured("google"),
            "github_enabled": oauth.is_provider_configured("github"),
        })

    clear_client_login_attempts(client_ip, email_key)
    token = create_client_token(account.id)
    response = RedirectResponse("/client/portal", status_code=303)
    response.set_cookie(CLIENT_COOKIE_NAME, token, httponly=True, samesite="lax", secure=COOKIE_SECURE)
    return response


@router.get("/client/logout")
def client_logout():
    response = RedirectResponse("/client/login", status_code=303)
    response.delete_cookie(CLIENT_COOKIE_NAME)
    return response


# ── Connexion OAuth (Google / GitHub) ───────────────────────────────────────

@router.get("/client/auth/{provider}")
def client_oauth_start(provider: str, request: Request):
    if provider not in oauth.PROVIDERS or not oauth.is_provider_configured(provider):
        return RedirectResponse("/client/login?error=oauth_unavailable", status_code=303)
    state = oauth.generate_state()
    url = oauth.get_authorize_url(provider, state)
    response = RedirectResponse(url, status_code=303)
    response.set_cookie(OAUTH_STATE_COOKIE, state, httponly=True, samesite="lax", max_age=600, secure=COOKIE_SECURE)
    return response


@router.get("/client/auth/{provider}/callback")
def client_oauth_callback(
    provider: str,
    request: Request,
    code: str = "",
    state: str = "",
    session: Session = Depends(get_session),
):
    if provider not in oauth.PROVIDERS:
        raise HTTPException(status_code=404, detail="Provider OAuth inconnu")
    expected_state = request.cookies.get(OAUTH_STATE_COOKIE)
    if not code or not state or not expected_state or state != expected_state:
        return RedirectResponse("/client/login?error=oauth_state", status_code=303)

    profile = oauth.fetch_oauth_profile(provider, code)
    if not profile:
        return RedirectResponse("/client/login?error=oauth_failed", status_code=303)

    account = session.scalars(select(ClientAccount).where(ClientAccount.email == profile.email, ClientAccount.is_active)).first()
    if not account:
        # Règle de sécurité : pas de création de compte à la volée. L'atelier doit
        # avoir déjà activé l'espace client pour cet email.
        logger.info("Connexion OAuth refusée (compte inconnu) : %s via %s", profile.email, provider)
        response = RedirectResponse("/client/login?error=unknown_account", status_code=303)
        response.delete_cookie(OAUTH_STATE_COOKIE)
        return response

    existing_identity = session.scalars(
        select(ClientOAuthIdentity).where(
            ClientOAuthIdentity.provider == provider,
            ClientOAuthIdentity.provider_user_id == profile.provider_user_id,
        )
    ).first()
    if not existing_identity:
        session.add(ClientOAuthIdentity(
            client_account_id=account.id, provider=provider, provider_user_id=profile.provider_user_id,
        ))
        session.commit()

    token = create_client_token(account.id)
    response = RedirectResponse("/client/portal", status_code=303)
    response.set_cookie(CLIENT_COOKIE_NAME, token, httponly=True, samesite="lax", secure=COOKIE_SECURE)
    response.delete_cookie(OAUTH_STATE_COOKIE)
    return response


# ── Portail client ───────────────────────────────────────────────────────────

@router.get("/client/portal", response_class=HTMLResponse)
def client_portal_home(request: Request, session: Session = Depends(get_session)):
    account, redirect = get_client_or_redirect(request, session)
    if redirect:
        return redirect
    client = account.client
    interventions = session.scalars(
        select(Intervention).where(Intervention.client_id == client.id).order_by(Intervention.created_at.desc())
    ).all()
    quotes = session.scalars(
        select(Quote).where(Quote.client_id == client.id).order_by(Quote.created_at.desc())
    ).all()
    invoices = session.scalars(
        select(Invoice).where(Invoice.client_id == client.id).order_by(Invoice.created_at.desc())
    ).all()
    upcoming_appointments = session.scalars(
        select(Appointment).where(
            Appointment.client_id == client.id, Appointment.start_at >= datetime.now(timezone.utc)
        ).order_by(Appointment.start_at.asc())
    ).all()
    return _templates.TemplateResponse("client/portal.html", {
        "request": request,
        "account": account,
        "client": client,
        "interventions": interventions,
        "quotes": quotes,
        "invoices": invoices,
        "upcoming_appointments": upcoming_appointments,
    })


@router.post("/client/portal/change-password")
def client_change_password(
    request: Request,
    current_password: str = Form(...),
    new_password: str = Form(...),
    confirm_password: str = Form(...),
    session: Session = Depends(get_session),
):
    account, redirect = get_client_or_redirect(request, session)
    if redirect:
        return redirect
    if not account.hashed_password or not verify_password(current_password, account.hashed_password):
        return RedirectResponse("/client/portal?pwd=current_invalid", status_code=303)
    if new_password != confirm_password:
        return RedirectResponse("/client/portal?pwd=mismatch", status_code=303)
    error = validate_password_strength(new_password, account.email)
    if error:
        return RedirectResponse("/client/portal?pwd=weak", status_code=303)
    account.hashed_password = hash_password(new_password)
    session.commit()
    return RedirectResponse("/client/portal?pwd=ok", status_code=303)


@router.get("/client/quote/{quote_id}/pdf")
def client_quote_pdf(quote_id: int, request: Request, session: Session = Depends(get_session)):
    account, redirect = get_client_or_redirect(request, session)
    if redirect:
        return redirect
    quote = session.scalars(select(Quote).where(Quote.id == quote_id)).first()
    if not quote or quote.client_id != account.client_id:
        raise HTTPException(status_code=404, detail="Devis introuvable")
    return try_pdf_response(quote_html(quote), f"{quote.quote_number}.pdf")


@router.post("/client/quote/{quote_id}/accept")
def client_accept_quote(quote_id: int, request: Request, session: Session = Depends(get_session)):
    """Le client accepte le devis → statut accepted + facture brouillon créée."""
    account, redirect = get_client_or_redirect(request, session)
    if redirect:
        return redirect
    quote = session.scalars(select(Quote).where(Quote.id == quote_id)).first()
    if not quote or quote.client_id != account.client_id:
        raise HTTPException(status_code=404, detail="Devis introuvable")
    if quote.status in {"cancelled", "rejected"}:
        return RedirectResponse("/client/portal?quote=not_acceptable", status_code=303)

    existing = session.scalars(select(Invoice).where(Invoice.quote_id == quote_id)).first()
    if existing:
        quote.status = "accepted"
        session.commit()
        return RedirectResponse(f"/client/portal?quote=accepted&invoice={existing.id}", status_code=303)

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
    session.commit()
    logger.info(
        "Client %s a accepté le devis %s → facture %s",
        account.client_id, quote.quote_number, invoice.invoice_number,
    )
    return RedirectResponse(f"/client/portal?quote=accepted&invoice={invoice.id}", status_code=303)


@router.get("/client/invoice/{invoice_id}/pdf")
def client_invoice_pdf(invoice_id: int, request: Request, session: Session = Depends(get_session)):
    account, redirect = get_client_or_redirect(request, session)
    if redirect:
        return redirect
    invoice = session.scalars(select(Invoice).where(Invoice.id == invoice_id)).first()
    if not invoice or invoice.client_id != account.client_id:
        raise HTTPException(status_code=404, detail="Facture introuvable")
    return try_pdf_response(invoice_html(invoice), f"{invoice.invoice_number}.pdf")


# ── Administration de l'espace client (depuis la fiche client staff) ───────

def _generate_temp_password() -> str:
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(14))


@router.post("/client/{client_id}/portal/enable")
def enable_client_portal(
    client_id: int,
    request: Request,
    email: str = Form(...),
    session: Session = Depends(get_session),
):
    # Technicien ou admin : activation quotidienne depuis la fiche client.
    admin, redirect = get_user_or_redirect(request, session)
    if redirect:
        return redirect
    client = session.scalars(select(Client).where(Client.id == client_id)).first()
    if not client:
        raise HTTPException(status_code=404, detail="Client introuvable")

    email_clean = email.strip().lower()
    existing = session.scalars(select(ClientAccount).where(ClientAccount.client_id == client_id)).first()
    temp_password = _generate_temp_password()
    if existing:
        existing.email = email_clean
        existing.hashed_password = hash_password(temp_password)
        existing.is_active = True
        account = existing
    else:
        if session.scalars(select(ClientAccount).where(ClientAccount.email == email_clean)).first():
            return RedirectResponse(f"/client/{client_id}?portal=email_taken", status_code=303)
        account = ClientAccount(client_id=client_id, email=email_clean, hashed_password=hash_password(temp_password), is_active=True)
        session.add(account)

    log_activity(session, admin, "client_portal.enable", f"client#{client_id} {email_clean}")
    session.commit()

    if _send_email_fn:
        login_url = f"{oauth.redirect_base()}/client/login"
        body = (
            f"Bonjour {client.name},\n\n"
            "Votre espace client Restor-PC est maintenant actif. Vous pouvez y consulter "
            "vos devis, factures et interventions.\n\n"
            f"Identifiant : {email_clean}\n"
            f"Mot de passe temporaire : {temp_password}\n\n"
            f"Connectez-vous ici : {login_url}\n"
            "Nous vous recommandons de changer ce mot de passe dès votre première connexion.\n\n"
            "Cordialement,\nRESTOR-PC\ncontact@restor-pc.fr"
        )
        ok, detail = _send_email_fn(
            to_email=email_clean,
            subject="Votre espace client Restor-PC est activé",
            body=body,
            html_attachment=f"<p>Identifiant : {email_clean}<br>Mot de passe temporaire : {temp_password}</p>",
            attachment_name="acces-espace-client.pdf",
        )
        if not ok:
            logger.warning("Email activation espace client non envoyé (%s) : %s", email_clean, detail)

    return RedirectResponse(f"/client/{client_id}?portal=enabled", status_code=303)


@router.post("/client/{client_id}/portal/disable")
def disable_client_portal(client_id: int, request: Request, session: Session = Depends(get_session)):
    admin, redirect = get_admin_or_redirect(request, session)
    if redirect:
        return redirect
    account = session.scalars(select(ClientAccount).where(ClientAccount.client_id == client_id)).first()
    if account:
        account.is_active = False
        log_activity(session, admin, "client_portal.disable", f"client#{client_id}")
        session.commit()
    return RedirectResponse(f"/client/{client_id}?portal=disabled", status_code=303)


@router.post("/client/{client_id}/portal/reset-password")
def reset_client_portal_password(client_id: int, request: Request, session: Session = Depends(get_session)):
    admin, redirect = get_admin_or_redirect(request, session)
    if redirect:
        return redirect
    account = session.scalars(select(ClientAccount).where(ClientAccount.client_id == client_id)).first()
    if not account:
        raise HTTPException(status_code=404, detail="Aucun compte espace client pour ce client")
    temp_password = _generate_temp_password()
    account.hashed_password = hash_password(temp_password)
    account.is_active = True
    log_activity(session, admin, "client_portal.reset_password", f"client#{client_id}")
    session.commit()

    if _send_email_fn:
        client = account.client
        login_url = f"{oauth.redirect_base()}/client/login"
        body = (
            f"Bonjour {client.name if client else ''},\n\n"
            f"Votre mot de passe d'accès à l'espace client Restor-PC a été réinitialisé.\n\n"
            f"Identifiant : {account.email}\n"
            f"Nouveau mot de passe temporaire : {temp_password}\n\n"
            f"Connectez-vous ici : {login_url}\n\n"
            "Cordialement,\nRESTOR-PC\ncontact@restor-pc.fr"
        )
        ok, detail = _send_email_fn(
            to_email=account.email,
            subject="Réinitialisation de votre mot de passe — espace client Restor-PC",
            body=body,
            html_attachment=f"<p>Nouveau mot de passe temporaire : {temp_password}</p>",
            attachment_name="reinitialisation-espace-client.pdf",
        )
        if not ok:
            logger.warning("Email reset password espace client non envoyé (%s) : %s", account.email, detail)

    return RedirectResponse(f"/client/{client_id}?portal=reset", status_code=303)

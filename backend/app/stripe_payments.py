"""
stripe_payments.py — Lien de paiement en ligne (Stripe Checkout) sur les factures
-----------------------------------------------------------------------------------
Fonctionnalité entièrement optionnelle : sans `STRIPE_SECRET_KEY` configurée,
`ensure_payment_link()` ne fait rien (retourne None) et le comportement de
l'application est strictement identique à avant cette fonctionnalité.

Confirmation de paiement par webhook Stripe (`checkout.session.completed`) :
voir `verify_and_handle_webhook()`, appelée depuis `POST /stripe/webhook`
(app/main.py). Le montant/devise viennent directement de la facture — pas de
Payment Link statique unique, une nouvelle Session est créée par facture (avec
mise en cache ~23h, une Session Stripe expirant après 24h).
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from . import oauth
from .auth import log_activity
from .models import Invoice

logger = logging.getLogger(__name__)

STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY", "").strip()
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET", "").strip()

# Marge de sécurité sous la durée de vie réelle d'une Session Stripe (24h).
_LINK_LIFETIME = timedelta(hours=23)


def stripe_enabled() -> bool:
    return bool(STRIPE_SECRET_KEY)


def _stripe_module():
    """Import paresseux : évite tout crash au démarrage si le paquet `stripe`
    n'est pas installé (ex. environnement de test) et que la fonctionnalité
    n'est pas utilisée."""
    import stripe

    stripe.api_key = STRIPE_SECRET_KEY
    return stripe


def ensure_payment_link(session: Session, invoice: Invoice) -> str | None:
    """Retourne une URL de paiement Stripe Checkout pour cette facture, en la
    créant (ou la renouvelant si expirée) si besoin.

    Retourne None si Stripe n'est pas configuré, si la facture est déjà
    payée/annulée, ou si la création de la session échoue (l'appelant doit
    alors se comporter comme si le paiement en ligne n'existait pas — jamais
    bloquer l'envoi d'un devis/facture pour cette raison).
    """
    if not stripe_enabled():
        return None
    if invoice.status in ("paid", "cancelled"):
        return None

    now = datetime.now(timezone.utc)
    if (
        invoice.stripe_payment_link_url
        and invoice.stripe_link_expires_at
        and invoice.stripe_link_expires_at > now
    ):
        return invoice.stripe_payment_link_url

    try:
        stripe = _stripe_module()
        base_url = oauth.redirect_base()
        client = invoice.client
        checkout_session = stripe.checkout.Session.create(
            mode="payment",
            payment_method_types=["card"],
            line_items=[
                {
                    "price_data": {
                        "currency": "eur",
                        "product_data": {"name": f"Facture Restor-PC {invoice.invoice_number}"},
                        "unit_amount": round(invoice.total * 100),
                    },
                    "quantity": 1,
                }
            ],
            metadata={"invoice_id": str(invoice.id), "invoice_number": invoice.invoice_number},
            customer_email=(client.email if client and client.email else None),
            success_url=f"{base_url}/pay/success?invoice={invoice.invoice_number}",
            cancel_url=f"{base_url}/pay/cancel?invoice={invoice.invoice_number}",
        )
    except Exception:
        logger.exception(
            "Création du lien de paiement Stripe impossible pour la facture %s",
            invoice.invoice_number,
        )
        return None

    invoice.stripe_checkout_session_id = checkout_session.id
    invoice.stripe_payment_link_url = checkout_session.url
    invoice.stripe_link_expires_at = now + _LINK_LIFETIME
    session.commit()
    return invoice.stripe_payment_link_url


def verify_and_handle_webhook(payload: bytes, sig_header: str, session: Session) -> bool:
    """Vérifie la signature du webhook Stripe et marque la facture correspondante
    comme payée sur l'événement `checkout.session.completed`.

    Retourne True si la signature est valide (même si l'événement n'était pas
    exploitable, ex. metadata manquante), False si la signature est invalide —
    l'appelant renvoie alors un 400 à Stripe sans exposer le détail de l'erreur.
    """
    if not STRIPE_WEBHOOK_SECRET:
        logger.warning("Webhook Stripe reçu mais STRIPE_WEBHOOK_SECRET n'est pas configuré — ignoré.")
        return False

    stripe = _stripe_module()
    try:
        event = stripe.Webhook.construct_event(payload, sig_header, STRIPE_WEBHOOK_SECRET)
    except Exception as exc:
        logger.warning("Signature webhook Stripe invalide : %s", exc)
        return False

    if event["type"] == "checkout.session.completed":
        data = event["data"]["object"]
        invoice_id = (data.get("metadata") or {}).get("invoice_id")
        if not invoice_id:
            logger.warning("Webhook Stripe checkout.session.completed sans metadata.invoice_id")
            return True
        invoice = session.get(Invoice, int(invoice_id))
        if invoice and invoice.status != "paid":
            invoice.status = "paid"
            invoice.paid_at = datetime.now(timezone.utc)
            invoice.payment_method = "stripe"
            log_activity(session, None, "invoice.pay_stripe", invoice.invoice_number)
            session.commit()
            logger.info("Facture %s marquée payée via webhook Stripe", invoice.invoice_number)

    return True

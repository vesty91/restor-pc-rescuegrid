"""Envoi SMTP unifié (Infomaniak / variables MAIL_* et SMTP_*)."""
from __future__ import annotations

import logging
import os
import smtplib
from email.message import EmailMessage
from email.utils import formataddr

from ..helpers import render_document_pdf

logger = logging.getLogger(__name__)


def smtp_config() -> dict:
    """Configuration SMTP unifiée, compatible Infomaniak et anciens noms SMTP_*."""
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


# Alias historique (backup.py, routes_v10)
_smtp_config = smtp_config


def send_document_email(
    *,
    to_email: str,
    subject: str,
    body: str,
    html_attachment: str,
    attachment_name: str,
) -> tuple[bool, str]:
    """Envoi SMTP. Attache un PDF si possible, sinon un HTML imprimable."""
    cfg = smtp_config()
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
        logger.warning("Échec SMTP to=%s: %s", to_email, exc)
        return False, f"smtp_error:{exc}"

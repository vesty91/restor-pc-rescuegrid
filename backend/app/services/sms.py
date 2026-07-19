"""Envoi SMS / WhatsApp optionnel via Twilio (RDV, rappels).

Configurer dans .env :
  TWILIO_ACCOUNT_SID=...
  TWILIO_AUTH_TOKEN=...
  TWILIO_FROM=+33...          # numéro SMS Twilio
  TWILIO_WHATSAPP_FROM=whatsapp:+14155238886   # optionnel (sandbox ou numéro WA)

Sans ces variables, send_sms / send_whatsapp retournent un code d'erreur clair.
"""
from __future__ import annotations

import logging
import os
import re
from urllib.parse import urlencode
from urllib.request import Request, urlopen

logger = logging.getLogger(__name__)


def _twilio_cfg() -> dict:
    return {
        "sid": (os.getenv("TWILIO_ACCOUNT_SID") or "").strip(),
        "token": (os.getenv("TWILIO_AUTH_TOKEN") or "").strip(),
        "from_sms": (os.getenv("TWILIO_FROM") or "").strip(),
        "from_wa": (os.getenv("TWILIO_WHATSAPP_FROM") or "").strip(),
    }


def sms_configured() -> bool:
    c = _twilio_cfg()
    return bool(c["sid"] and c["token"] and c["from_sms"])


def whatsapp_configured() -> bool:
    c = _twilio_cfg()
    return bool(c["sid"] and c["token"] and c["from_wa"])


def _normalize_fr_phone(phone: str) -> str | None:
    if not phone:
        return None
    digits = re.sub(r"[^\d+]", "", phone.strip())
    if digits.startswith("00"):
        digits = "+" + digits[2:]
    if digits.startswith("0") and len(digits) == 10:
        digits = "+33" + digits[1:]
    if not digits.startswith("+"):
        return None
    if len(re.sub(r"\D", "", digits)) < 10:
        return None
    return digits


def _twilio_send(to: str, body: str, from_number: str) -> tuple[bool, str]:
    cfg = _twilio_cfg()
    if not cfg["sid"] or not cfg["token"]:
        return False, "twilio_not_configured"
    if not from_number:
        return False, "twilio_from_missing"
    url = f"https://api.twilio.com/2010-04-01/Accounts/{cfg['sid']}/Messages.json"
    data = urlencode({"To": to, "From": from_number, "Body": body}).encode("utf-8")
    req = Request(url, data=data, method="POST")
    import base64

    token = base64.b64encode(f"{cfg['sid']}:{cfg['token']}".encode("utf-8")).decode("ascii")
    req.add_header("Authorization", f"Basic {token}")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    try:
        with urlopen(req, timeout=20) as resp:
            if 200 <= resp.status < 300:
                return True, "sent"
            return False, f"twilio_http_{resp.status}"
    except Exception as exc:  # noqa: BLE001
        logger.warning("Twilio send failed: %s", exc)
        return False, "twilio_error"


def send_sms(to_phone: str, body: str) -> tuple[bool, str]:
    """Envoie un SMS. Retourne (ok, detail)."""
    if not sms_configured():
        return False, "sms_not_configured"
    to = _normalize_fr_phone(to_phone)
    if not to:
        return False, "invalid_phone"
    text = (body or "").strip()
    if len(text) > 480:
        text = text[:477] + "..."
    return _twilio_send(to, text, _twilio_cfg()["from_sms"])


def send_whatsapp(to_phone: str, body: str) -> tuple[bool, str]:
    """Envoie un message WhatsApp via Twilio. Retourne (ok, detail)."""
    if not whatsapp_configured():
        return False, "whatsapp_not_configured"
    to = _normalize_fr_phone(to_phone)
    if not to:
        return False, "invalid_phone"
    to_wa = to if to.startswith("whatsapp:") else f"whatsapp:{to}"
    text = (body or "").strip()
    if len(text) > 1000:
        text = text[:997] + "..."
    return _twilio_send(to_wa, text, _twilio_cfg()["from_wa"])

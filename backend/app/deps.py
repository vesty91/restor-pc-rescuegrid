"""
app/deps.py — Restor-PC RescueGrid
------------------------------------
Ré-exporte les dépendances depuis auth.py pour éviter les imports circulaires.
"""
from __future__ import annotations

import ipaddress
import logging
import os
import re

from .auth import get_user_or_redirect, get_current_user  # noqa: F401

logger = logging.getLogger(__name__)

# Défauts volontairement étroits : le backend Synology écoute en 127.0.0.1:8080
# (Reverse Proxy DSM) ou derrière nginx Docker (172.16/12). Les plages LAN
# entières (192.168/16, 10/8) ne sont PAS de confiance par défaut — un PC du
# LAN qui joindrait le port backend pourrait sinon spoof X-Forwarded-For.
# Étendre via TRUSTED_PROXY_CIDRS="192.168.1.5/32,10.0.0.0/8" si besoin.
_DEFAULT_TRUSTED_PROXY_CIDRS = (
    "127.0.0.1/32",
    "::1/128",
    "172.16.0.0/12",  # réseaux Docker bridge / compose
)

_IPV4_HOSTPORT = re.compile(r"^(\d{1,3}(?:\.\d{1,3}){3}):\d+$")


def _load_trusted_proxy_networks() -> list[ipaddress.IPv4Network | ipaddress.IPv6Network]:
    raw = (os.getenv("TRUSTED_PROXY_CIDRS") or "").strip()
    cidrs = [c.strip() for c in raw.split(",") if c.strip()] if raw else list(_DEFAULT_TRUSTED_PROXY_CIDRS)
    networks: list[ipaddress.IPv4Network | ipaddress.IPv6Network] = []
    for cidr in cidrs:
        try:
            networks.append(ipaddress.ip_network(cidr, strict=False))
        except ValueError:
            logger.warning("TRUSTED_PROXY_CIDRS ignore entrée invalide : %r", cidr)
    if not networks:
        logger.warning("TRUSTED_PROXY_CIDRS vide/invalide — repli sur les défauts sûrs")
        networks = [ipaddress.ip_network(c, strict=False) for c in _DEFAULT_TRUSTED_PROXY_CIDRS]
    return networks


# Chargé une fois à l'import (après dotenv via app/__init__.py).
TRUSTED_PROXY_NETWORKS = _load_trusted_proxy_networks()


def reload_trusted_proxy_networks() -> list[ipaddress.IPv4Network | ipaddress.IPv6Network]:
    """Recharge depuis l'environnement (tests)."""
    global TRUSTED_PROXY_NETWORKS
    TRUSTED_PROXY_NETWORKS = _load_trusted_proxy_networks()
    return TRUSTED_PROXY_NETWORKS


def _is_trusted_proxy(peer_ip: str) -> bool:
    try:
        addr = ipaddress.ip_address(peer_ip)
    except ValueError:
        return False
    return any(addr in net for net in TRUSTED_PROXY_NETWORKS)


def _normalize_ip_token(token: str) -> str | None:
    """Valide un jeton X-Forwarded-For / X-Real-IP ; None si invalide."""
    value = (token or "").strip().strip('"').strip("'")
    if not value or value.lower() in {"unknown", "null"}:
        return None
    # [IPv6] ou [IPv6]:port
    if value.startswith("["):
        end = value.find("]")
        if end > 1:
            value = value[1:end]
    else:
        m = _IPV4_HOSTPORT.match(value)
        if m:
            value = m.group(1)
    try:
        # Refuse IPs non routables bizarres ? Non — on accepte toute IP syntaxiquement valide.
        return str(ipaddress.ip_address(value))
    except ValueError:
        return None


def get_client_ip(request) -> str:
    """
    Adresse IP réelle du client, pour le rate limiting / verrouillage de compte.

    On ne fait confiance à `X-Forwarded-For` / `X-Real-IP` que si la connexion TCP
    directe provient d'un proxy de confiance (`TRUSTED_PROXY_CIDRS`).
    L'IP extraite est validée (sinon on garde l'IP TCP du peer).
    """
    peer_ip = request.client.host if request.client else None
    if not peer_ip:
        return "unknown"

    if not _is_trusted_proxy(peer_ip):
        return peer_ip

    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        # Chaîne "client, proxy1, proxy2" — le premier élément est l'origine client
        # (nginx append via $proxy_add_x_forwarded_for).
        for part in forwarded.split(","):
            parsed = _normalize_ip_token(part)
            if parsed:
                return parsed

    real_ip = request.headers.get("x-real-ip")
    if real_ip:
        parsed = _normalize_ip_token(real_ip)
        if parsed:
            return parsed

    return peer_ip

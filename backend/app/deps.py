"""
app/deps.py — Restor-PC RescueGrid
------------------------------------
Ré-exporte les dépendances depuis auth.py pour éviter les imports circulaires.
"""
import ipaddress

from .auth import get_user_or_redirect, get_current_user  # noqa: F401

# Le backend n'est jamais exposé directement à internet dans les déploiements
# documentés (voir docs/SYNOLOGY_DEPLOY.md) : il est toujours placé derrière le
# Nginx du compose Docker (réseau Docker interne) ou le Reverse Proxy DSM (qui
# se connecte depuis 127.0.0.1 sur le NAS). La connexion TCP directe vue par
# Uvicorn provient donc soit d'un de ces proxies de confiance, soit d'un client
# direct en développement local (aucun proxy, pas d'en-tête X-Forwarded-For).
_TRUSTED_PROXY_NETWORKS = [
    ipaddress.ip_network("127.0.0.1/32"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("172.16.0.0/12"),  # plages par défaut des réseaux Docker
    ipaddress.ip_network("192.168.0.0/16"),  # LAN (NAS, conteneur nginx exposé en LAN)
    ipaddress.ip_network("10.0.0.0/8"),
]


def _is_trusted_proxy(peer_ip: str) -> bool:
    try:
        addr = ipaddress.ip_address(peer_ip)
    except ValueError:
        return False
    return any(addr in net for net in _TRUSTED_PROXY_NETWORKS)


def get_client_ip(request) -> str:
    """
    Adresse IP réelle du client, pour le rate limiting / verrouillage de compte.

    On ne fait confiance à l'en-tête `X-Forwarded-For` que si la connexion TCP
    directe provient elle-même d'un proxy de confiance (voir ci-dessus) —
    sinon n'importe quel client distant pourrait falsifier cet en-tête pour
    se faire passer pour une IP arbitraire et contourner le rate limiting.
    Sans cette vérification, un attaquant derrière le proxy verrait aussi son
    adresse "de confiance" (127.0.0.1 ou l'IP du proxy) partagée par tous les
    vrais utilisateurs, ce qui casserait le rate-limit par IP pour tout le monde.
    """
    peer_ip = request.client.host if request.client else None
    if not peer_ip:
        return "unknown"

    if _is_trusted_proxy(peer_ip):
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            # X-Forwarded-For peut contenir une chaîne "client, proxy1, proxy2, ..."
            # — le premier élément est l'adresse d'origine du client.
            first = forwarded.split(",")[0].strip()
            if first:
                return first

    return peer_ip

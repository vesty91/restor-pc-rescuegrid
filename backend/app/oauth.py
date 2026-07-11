"""
oauth.py — Connexion Google / GitHub pour l'espace client
------------------------------------------------------------
Implémenté avec `httpx` (déjà une dépendance du projet) plutôt qu'une librairie
OAuth dédiée, pour rester minimal. Flux "authorization code" standard.

Sécurité : ce module ne fait QUE récupérer l'email (et l'identifiant provider)
de l'utilisateur connecté côté Google/GitHub. C'est routes/client_portal.py qui
décide si cet email correspond à un ClientAccount existant — voir la règle de
sécurité dans le plan (pas de création de compte à la volée par un inconnu).
"""
from __future__ import annotations

import logging
import os
import secrets
from dataclasses import dataclass

import httpx

logger = logging.getLogger(__name__)


@dataclass
class OAuthProfile:
    email: str
    provider_user_id: str


def _redirect_base() -> str:
    return os.getenv("OAUTH_REDIRECT_BASE_URL", "http://localhost:8000").rstrip("/")


def redirect_uri(provider: str) -> str:
    return f"{_redirect_base()}/client/auth/{provider}/callback"


def generate_state() -> str:
    return secrets.token_urlsafe(24)


PROVIDERS = {
    "google": {
        "client_id_env": "GOOGLE_CLIENT_ID",
        "client_secret_env": "GOOGLE_CLIENT_SECRET",
        "authorize_url": "https://accounts.google.com/o/oauth2/v2/auth",
        "token_url": "https://oauth2.googleapis.com/token",
        "userinfo_url": "https://www.googleapis.com/oauth2/v3/userinfo",
        "scope": "openid email profile",
    },
    "github": {
        "client_id_env": "GITHUB_CLIENT_ID",
        "client_secret_env": "GITHUB_CLIENT_SECRET",
        "authorize_url": "https://github.com/login/oauth/authorize",
        "token_url": "https://github.com/login/oauth/access_token",
        "userinfo_url": "https://api.github.com/user",
        "scope": "read:user user:email",
    },
}


def is_provider_configured(provider: str) -> bool:
    cfg = PROVIDERS.get(provider)
    if not cfg:
        return False
    return bool(os.getenv(cfg["client_id_env"]) and os.getenv(cfg["client_secret_env"]))


def get_authorize_url(provider: str, state: str) -> str:
    cfg = PROVIDERS[provider]
    client_id = os.getenv(cfg["client_id_env"], "")
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri(provider),
        "scope": cfg["scope"],
        "state": state,
        "response_type": "code",
    }
    if provider == "google":
        params["access_type"] = "online"
        params["prompt"] = "select_account"
    return httpx.URL(cfg["authorize_url"], params=params).human_repr()


def _exchange_code_google(code: str) -> str | None:
    cfg = PROVIDERS["google"]
    data = {
        "client_id": os.getenv(cfg["client_id_env"], ""),
        "client_secret": os.getenv(cfg["client_secret_env"], ""),
        "code": code,
        "grant_type": "authorization_code",
        "redirect_uri": redirect_uri("google"),
    }
    resp = httpx.post(cfg["token_url"], data=data, timeout=15)
    if resp.status_code != 200:
        logger.warning("Échange token Google échoué : %s", resp.text[:300])
        return None
    return resp.json().get("access_token")


def _exchange_code_github(code: str) -> str | None:
    cfg = PROVIDERS["github"]
    data = {
        "client_id": os.getenv(cfg["client_id_env"], ""),
        "client_secret": os.getenv(cfg["client_secret_env"], ""),
        "code": code,
        "redirect_uri": redirect_uri("github"),
    }
    resp = httpx.post(cfg["token_url"], data=data, headers={"Accept": "application/json"}, timeout=15)
    if resp.status_code != 200:
        logger.warning("Échange token GitHub échoué : %s", resp.text[:300])
        return None
    return resp.json().get("access_token")


def _profile_google(access_token: str) -> OAuthProfile | None:
    resp = httpx.get(
        PROVIDERS["google"]["userinfo_url"],
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=15,
    )
    if resp.status_code != 200:
        return None
    data = resp.json()
    email = data.get("email")
    if not email or not data.get("email_verified", True):
        return None
    return OAuthProfile(email=email.strip().lower(), provider_user_id=str(data.get("sub") or email))


def _profile_github(access_token: str) -> OAuthProfile | None:
    headers = {"Authorization": f"token {access_token}", "Accept": "application/vnd.github+json"}
    user_resp = httpx.get(PROVIDERS["github"]["userinfo_url"], headers=headers, timeout=15)
    if user_resp.status_code != 200:
        return None
    user_data = user_resp.json()
    provider_user_id = str(user_data.get("id"))

    # Sécurité : on ne fait jamais confiance directement au champ "email" de
    # /user (public profile), même s'il est présent — on ne retient que les
    # adresses explicitement marquées "verified" par /user/emails. GitHub exige
    # déjà qu'une adresse soit vérifiée pour être associée à un compte, mais on
    # revérifie ici en défense en profondeur plutôt que de se fier à un champ
    # qui ne porte pas lui-même l'information de vérification.
    verified_emails: list[dict] = []
    emails_resp = httpx.get("https://api.github.com/user/emails", headers=headers, timeout=15)
    if emails_resp.status_code == 200:
        verified_emails = [e for e in emails_resp.json() if e.get("verified")]

    email = None
    for entry in verified_emails:
        if entry.get("primary"):
            email = entry.get("email")
            break
    if not email and verified_emails:
        email = verified_emails[0].get("email")

    if not email:
        logger.warning("Connexion GitHub refusée : aucune adresse email vérifiée pour l'utilisateur #%s", provider_user_id)
        return None
    return OAuthProfile(email=email.strip().lower(), provider_user_id=provider_user_id)


def fetch_oauth_profile(provider: str, code: str) -> OAuthProfile | None:
    """Échange le code d'autorisation contre le profil (email + id provider)."""
    if provider == "google":
        token = _exchange_code_google(code)
        return _profile_google(token) if token else None
    if provider == "github":
        token = _exchange_code_github(code)
        return _profile_github(token) if token else None
    return None

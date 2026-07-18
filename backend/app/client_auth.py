"""
client_auth.py — Authentification de l'espace client (Restor-PC RescueGrid)
----------------------------------------------------------------------------
Séparé de app/auth.py (authentification staff) par sécurité : un cookie client
ne doit jamais donner accès au back-office, et inversement.

- Cookie dédié `client_token` (distinct du cookie staff `access_token`).
- JWT avec un claim `"typ": "client"` pour empêcher toute confusion/rejeu
  entre les deux espaces même si un token venait à être intercepté.
- Rate limit + verrouillage de compte persistants (voir app/rate_limit.py).
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import Request
from fastapi.responses import RedirectResponse
from jose import JWTError, jwt
from sqlalchemy import select
from sqlalchemy.orm import Session

from .auth import SECRET_KEY, ALGORITHM, verify_password
from .models import ClientAccount
from .rate_limit import clear_bucket, is_rate_limited, record_hit

logger = logging.getLogger(__name__)

CLIENT_TOKEN_EXPIRE_MINUTES = int(os.getenv("CLIENT_TOKEN_EXPIRE_MINUTES", "1440"))
CLIENT_COOKIE_NAME = "client_token"

CLIENT_LOGIN_RATE_LIMIT_COUNT = int(os.getenv("CLIENT_LOGIN_RATE_LIMIT_COUNT", "5"))
CLIENT_LOGIN_RATE_LIMIT_WINDOW_SECONDS = int(os.getenv("CLIENT_LOGIN_RATE_LIMIT_WINDOW_SECONDS", "300"))
CLIENT_ACCOUNT_LOCKOUT_COUNT = int(os.getenv("CLIENT_ACCOUNT_LOCKOUT_COUNT", "5"))
CLIENT_ACCOUNT_LOCKOUT_WINDOW_SECONDS = int(os.getenv("CLIENT_ACCOUNT_LOCKOUT_WINDOW_SECONDS", "900"))


def is_client_rate_limited(client_ip: str) -> bool:
    return is_rate_limited(
        f"client_login_ip:{client_ip}",
        max_count=CLIENT_LOGIN_RATE_LIMIT_COUNT,
        window_seconds=CLIENT_LOGIN_RATE_LIMIT_WINDOW_SECONDS,
    )


def is_client_account_locked(email_key: str) -> bool:
    if not email_key:
        return False
    return is_rate_limited(
        f"client_login_user:{email_key}",
        max_count=CLIENT_ACCOUNT_LOCKOUT_COUNT,
        window_seconds=CLIENT_ACCOUNT_LOCKOUT_WINDOW_SECONDS,
    )


def record_client_login_failure(client_ip: str, email_key: str) -> None:
    record_hit(f"client_login_ip:{client_ip}", window_seconds=CLIENT_LOGIN_RATE_LIMIT_WINDOW_SECONDS)
    if email_key:
        record_hit(f"client_login_user:{email_key}", window_seconds=CLIENT_ACCOUNT_LOCKOUT_WINDOW_SECONDS)


def clear_client_login_attempts(client_ip: str, email_key: str) -> None:
    clear_bucket(f"client_login_ip:{client_ip}")
    if email_key:
        clear_bucket(f"client_login_user:{email_key}")


def create_client_token(client_account_id: int) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=CLIENT_TOKEN_EXPIRE_MINUTES)
    payload = {"sub": str(client_account_id), "typ": "client", "exp": expire}
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def decode_client_token(token: str) -> Optional[dict]:
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError:
        return None
    if payload.get("typ") != "client":
        return None
    return payload


def authenticate_client_account(email: str, password: str, session: Session) -> Optional[ClientAccount]:
    account = session.scalars(
        select(ClientAccount).where(
            ClientAccount.email == email.strip().lower(),
            ClientAccount.is_active == True,  # noqa: E712
        )
    ).first()
    if not account or not account.hashed_password:
        return None
    if not verify_password(password, account.hashed_password):
        return None
    return account


def get_current_client(request: Request, session: Session) -> Optional[ClientAccount]:
    token = request.cookies.get(CLIENT_COOKIE_NAME)
    if not token:
        return None
    payload = decode_client_token(token)
    if not payload:
        return None
    try:
        account_id = int(payload.get("sub"))
    except (TypeError, ValueError):
        return None
    return session.scalars(
        select(ClientAccount).where(
            ClientAccount.id == account_id,
            ClientAccount.is_active == True,  # noqa: E712
        )
    ).first()


def client_login_redirect() -> RedirectResponse:
    return RedirectResponse("/client/login", status_code=303)


def get_client_or_redirect(
    request: Request, session: Session
) -> tuple[Optional[ClientAccount], Optional[RedirectResponse]]:
    account = get_current_client(request, session)
    if not account:
        return None, client_login_redirect()
    return account, None

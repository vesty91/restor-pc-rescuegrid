"""
client_auth.py — Authentification de l'espace client (Restor-PC RescueGrid)
----------------------------------------------------------------------------
Séparé de app/auth.py (authentification staff) par sécurité : un cookie client
ne doit jamais donner accès au back-office, et inversement.

- Cookie dédié `client_token` (distinct du cookie staff `access_token`).
- JWT avec un claim `"typ": "client"` pour empêcher toute confusion/rejeu
  entre les deux espaces même si un token venait à être intercepté.
- Rate limit + verrouillage de compte, sur le même principe que /login.
"""
from __future__ import annotations

import logging
import os
import time
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import Request
from fastapi.responses import RedirectResponse
from jose import JWTError, jwt
from sqlalchemy import select
from sqlalchemy.orm import Session

from .auth import SECRET_KEY, ALGORITHM, verify_password
from .models import ClientAccount

logger = logging.getLogger(__name__)

CLIENT_TOKEN_EXPIRE_MINUTES = int(os.getenv("CLIENT_TOKEN_EXPIRE_MINUTES", "1440"))
CLIENT_COOKIE_NAME = "client_token"

CLIENT_LOGIN_ATTEMPTS: dict[str, deque[float]] = defaultdict(deque)
CLIENT_LOGIN_RATE_LIMIT_COUNT = int(os.getenv("CLIENT_LOGIN_RATE_LIMIT_COUNT", "5"))
CLIENT_LOGIN_RATE_LIMIT_WINDOW_SECONDS = int(os.getenv("CLIENT_LOGIN_RATE_LIMIT_WINDOW_SECONDS", "300"))

CLIENT_ACCOUNT_LOCKOUT_ATTEMPTS: dict[str, deque[float]] = defaultdict(deque)
CLIENT_ACCOUNT_LOCKOUT_COUNT = int(os.getenv("CLIENT_ACCOUNT_LOCKOUT_COUNT", "5"))
CLIENT_ACCOUNT_LOCKOUT_WINDOW_SECONDS = int(os.getenv("CLIENT_ACCOUNT_LOCKOUT_WINDOW_SECONDS", "900"))


def is_client_rate_limited(client_ip: str) -> bool:
    now = time.time()
    attempts = CLIENT_LOGIN_ATTEMPTS[client_ip]
    while attempts and now - attempts[0] > CLIENT_LOGIN_RATE_LIMIT_WINDOW_SECONDS:
        attempts.popleft()
    return len(attempts) >= CLIENT_LOGIN_RATE_LIMIT_COUNT


def is_client_account_locked(email_key: str) -> bool:
    now = time.time()
    attempts = CLIENT_ACCOUNT_LOCKOUT_ATTEMPTS[email_key]
    while attempts and now - attempts[0] > CLIENT_ACCOUNT_LOCKOUT_WINDOW_SECONDS:
        attempts.popleft()
    return len(attempts) >= CLIENT_ACCOUNT_LOCKOUT_COUNT


def record_client_login_failure(client_ip: str, email_key: str) -> None:
    now = time.time()
    CLIENT_LOGIN_ATTEMPTS[client_ip].append(now)
    if email_key:
        CLIENT_ACCOUNT_LOCKOUT_ATTEMPTS[email_key].append(now)


def clear_client_login_attempts(client_ip: str, email_key: str) -> None:
    CLIENT_LOGIN_ATTEMPTS.pop(client_ip, None)
    CLIENT_ACCOUNT_LOCKOUT_ATTEMPTS.pop(email_key, None)


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
        # Empêche un cookie staff (access_token) d'être rejoué comme cookie client.
        return None
    return payload


def authenticate_client_account(email: str, password: str, session: Session) -> Optional[ClientAccount]:
    account = session.scalars(
        select(ClientAccount).where(ClientAccount.email == email.strip().lower(), ClientAccount.is_active == True)
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
    account = session.scalars(
        select(ClientAccount).where(ClientAccount.id == account_id, ClientAccount.is_active == True)
    ).first()
    return account


def client_login_redirect() -> RedirectResponse:
    return RedirectResponse("/client/login", status_code=303)


def get_client_or_redirect(request: Request, session: Session) -> tuple[Optional[ClientAccount], Optional[RedirectResponse]]:
    account = get_current_client(request, session)
    if not account:
        return None, client_login_redirect()
    return account, None

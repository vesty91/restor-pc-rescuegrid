"""
csrf.py — Jetons CSRF (double-submit cookie)

Le cookie `csrf_token` n'est PAS HttpOnly (lisible par le JS des templates pour
injecter le champ caché). Validation : cookie == champ formulaire `csrf_token`
(ou en-tête `X-CSRF-Token`). Origin/Referer reste vérifié en complément.
"""
from __future__ import annotations

import logging
import secrets
from urllib.parse import urlparse

from fastapi import Request
from fastapi.responses import JSONResponse, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request as StarletteRequest

logger = logging.getLogger(__name__)

CSRF_COOKIE = "csrf_token"
CSRF_FORM_FIELD = "csrf_token"
CSRF_HEADER = "x-csrf-token"
CSRF_UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
CSRF_EXEMPT_PATHS = {"/upload", "/stripe/webhook"}


def generate_csrf_token() -> str:
    return secrets.token_urlsafe(32)


def ensure_csrf_cookie(request: Request, response: Response) -> str:
    from .auth import COOKIE_SECURE

    existing = request.cookies.get(CSRF_COOKIE) or getattr(request.state, "csrf_token", None)
    if existing:
        token = existing
    else:
        token = generate_csrf_token()
    request.state.csrf_token = token
    response.set_cookie(
        key=CSRF_COOKIE,
        value=token,
        httponly=False,
        samesite="lax",
        secure=COOKIE_SECURE,
        path="/",
        max_age=60 * 60 * 12,
    )
    return token


def csrf_field_html(request: Request) -> str:
    token = request.cookies.get(CSRF_COOKIE) or getattr(request.state, "csrf_token", None)
    if not token:
        token = generate_csrf_token()
        request.state.csrf_token = token
    safe = token.replace('"', "&quot;")
    return f'<input type="hidden" name="{CSRF_FORM_FIELD}" value="{safe}">'


def _origin_ok(request: Request) -> bool:
    source = request.headers.get("origin") or request.headers.get("referer")
    if not source:
        return True
    source_host = urlparse(source).netloc
    expected_host = request.headers.get("host", "")
    if source_host and expected_host and source_host != expected_host:
        return False
    return True


async def _read_body(request: Request) -> bytes:
    body = await request.body()
    return body


def _request_with_body(request: Request, body: bytes) -> StarletteRequest:
    async def receive():
        return {"type": "http.request", "body": body, "more_body": False}

    return StarletteRequest(request.scope, receive)


async def _extract_submitted_token(request: Request, body: bytes) -> str | None:
    header = request.headers.get(CSRF_HEADER)
    if header:
        return header.strip() or None

    content_type = (request.headers.get("content-type") or "").lower()
    if "application/x-www-form-urlencoded" in content_type or "multipart/form-data" in content_type:
        replay = _request_with_body(request, body)
        form = await replay.form()
        value = form.get(CSRF_FORM_FIELD)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


class CsrfProtectMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        replay_request = request
        if request.method in CSRF_UNSAFE_METHODS and request.url.path not in CSRF_EXEMPT_PATHS:
            if not _origin_ok(request):
                logger.warning(
                    "CSRF origin invalide path=%s host=%s",
                    request.url.path,
                    request.headers.get("host"),
                )
                return JSONResponse(
                    {"detail": "Requête refusée : origine invalide (protection anti-CSRF)."},
                    status_code=403,
                )

            body = await _read_body(request)
            replay_request = _request_with_body(request, body)
            cookie_token = request.cookies.get(CSRF_COOKIE)
            submitted = await _extract_submitted_token(request, body)
            if (
                not cookie_token
                or not submitted
                or not secrets.compare_digest(cookie_token, submitted)
            ):
                logger.warning("CSRF jeton manquant/invalide path=%s", request.url.path)
                return JSONResponse(
                    {"detail": "Requête refusée : jeton CSRF manquant ou invalide."},
                    status_code=403,
                )

        response = await call_next(replay_request)
        ensure_csrf_cookie(request, response)
        return response

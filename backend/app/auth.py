"""
Authentification JWT pour Restor-PC RescueGrid
Roles : admin, technicien
"""
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Optional

import bcrypt
from fastapi import Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from jose import JWTError, jwt
from sqlalchemy import select
from sqlalchemy.orm import Session

from .database import get_session
from .models import ActivityLog, User

logger = logging.getLogger(__name__)

SECRET_KEY = os.getenv("SECRET_KEY", "rescuegrid-secret-change-in-production-2026")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("TOKEN_EXPIRE_MINUTES", "480"))

BCRYPT_ROUNDS = 12


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds=BCRYPT_ROUNDS)).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except (ValueError, TypeError):
        return False


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def decode_token(token: str) -> Optional[dict]:
    try:
        return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError:
        return None


def get_current_user(request: Request, session: Session = Depends(get_session)) -> Optional[User]:
    token = request.cookies.get("access_token")
    if not token:
        return None
    payload = decode_token(token)
    if not payload:
        return None
    username = payload.get("sub")
    if not username:
        return None
    user = session.scalars(select(User).where(User.username == username, User.is_active == True)).first()
    return user


def require_auth(user: Optional[User] = Depends(get_current_user)) -> User:
    if not user:
        raise HTTPException(status_code=status.HTTP_303_SEE_OTHER, headers={"Location": "/login"})
    return user


def require_admin(user: User = Depends(require_auth)) -> User:
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Acces administrateur requis")
    return user


def authenticate_user(username: str, password: str, session: Session) -> Optional[User]:
    user = session.scalars(select(User).where(User.username == username, User.is_active == True)).first()
    if not user or not verify_password(password, user.hashed_password):
        return None
    return user


def login_redirect() -> RedirectResponse:
    return RedirectResponse("/login", status_code=303)


def get_user_or_redirect(request: Request, session: Session) -> tuple[Optional[User], Optional[RedirectResponse]]:
    user = get_current_user(request, session)
    if not user:
        return None, login_redirect()
    return user, None


def get_admin_or_redirect(request: Request, session: Session) -> tuple[Optional[User], Optional[RedirectResponse]]:
    user, redirect = get_user_or_redirect(request, session)
    if redirect:
        return None, redirect
    if user.role != "admin":
        return None, RedirectResponse("/", status_code=303)
    return user, None


def verify_upload_access(request: Request, session: Session, upload_key: str | None = None) -> bool:
    """Autorise l'import ZIP si l'appelant est authentifié (session) ou possède la clé API.

    Sécurisé par défaut : si UPLOAD_API_KEY n'est pas configurée, l'upload anonyme
    est refusé. Pour un usage local/dev sans clé (agent sur le même poste, réseau
    de confiance), définir explicitement ALLOW_ANONYMOUS_UPLOAD=true.
    """
    if get_current_user(request, session):
        return True
    expected = os.getenv("UPLOAD_API_KEY", "").strip()
    if expected:
        if upload_key and upload_key == expected:
            return True
        return request.headers.get("X-Upload-Key", "") == expected
    return os.getenv("ALLOW_ANONYMOUS_UPLOAD", "").strip().lower() in {"1", "true", "yes", "on"}


def log_activity(session: Session, user: User | None, action: str, detail: str = "") -> None:
    session.add(ActivityLog(
        user_id=user.id if user else None,
        username=user.username if user else None,
        action=action,
        detail=detail[:2000] if detail else None,
    ))


def create_default_admin(session: Session) -> None:
    existing = session.scalars(select(User)).first()
    if existing:
        return
    admin_password = os.getenv("ADMIN_PASSWORD", "rescuegrid2026")
    admin = User(
        username="admin",
        hashed_password=hash_password(admin_password),
        full_name="Administrateur",
        role="admin",
        email="admin@rescuegrid.local",
    )
    session.add(admin)
    session.commit()
    logger.info("Compte administrateur par defaut cree : admin")

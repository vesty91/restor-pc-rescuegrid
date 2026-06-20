"""
Authentification JWT pour Restor-PC RescueGrid
Roles : admin, technicien
"""
import os
from datetime import datetime, timedelta
from typing import Optional

from fastapi import Cookie, Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy import select
from sqlalchemy.orm import Session

from .database import get_session
from .models import User

SECRET_KEY = os.getenv("SECRET_KEY", "rescuegrid-secret-change-in-production-2026")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("TOKEN_EXPIRE_MINUTES", "480"))  # 8h

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def decode_token(token: str) -> Optional[dict]:
    try:
        return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError:
        return None


def get_current_user(
    request: Request,
    session: Session = Depends(get_session),
) -> Optional["User"]:
    token = request.cookies.get("access_token")
    if not token:
        return None
    payload = decode_token(token)
    if not payload:
        return None
    username = payload.get("sub")
    if not username:
        return None
    user = session.scalars(select(User).where(User.username == username)).first()
    return user


def require_auth(user: Optional["User"] = Depends(get_current_user)) -> "User":
    if not user:
        raise HTTPException(
            status_code=status.HTTP_303_SEE_OTHER,
            headers={"Location": "/login"},
        )
    return user


def require_admin(user: "User" = Depends(require_auth)) -> "User":
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Acces administrateur requis")
    return user


def authenticate_user(username: str, password: str, session: Session) -> Optional["User"]:
    user = session.scalars(select(User).where(User.username == username)).first()
    if not user or not verify_password(password, user.hashed_password):
        return None
    return user


def login_redirect() -> RedirectResponse:
    return RedirectResponse("/login", status_code=303)


def get_user_or_redirect(
    request: Request,
    session: Session,
) -> tuple[Optional["User"], Optional[RedirectResponse]]:
    user = get_current_user(request, session)
    if not user:
        return None, login_redirect()
    return user, None


def get_admin_or_redirect(
    request: Request,
    session: Session,
) -> tuple[Optional["User"], Optional[RedirectResponse]]:
    user, redirect = get_user_or_redirect(request, session)
    if redirect:
        return None, redirect
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Acces administrateur requis")
    return user, None


def verify_upload_access(
    request: Request,
    session: Session,
    upload_key: str | None = None,
) -> bool:
    if get_current_user(request, session):
        return True
    expected = os.getenv("UPLOAD_API_KEY", "").strip()
    if not expected:
        return True
    if upload_key and upload_key == expected:
        return True
    header_key = request.headers.get("X-Upload-Key", "")
    return header_key == expected


def create_default_admin(session: Session) -> None:
    """Creer l'admin par defaut si aucun utilisateur n'existe."""
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
    print(f"[AUTH] Admin cree : admin / {admin_password}")
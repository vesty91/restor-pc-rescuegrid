"""
Authentification JWT pour Restor-PC RescueGrid
Roles : admin, technicien
"""
import logging
import os
import re
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path
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


def _load_or_create_secret_key() -> str:
    """Retourne SECRET_KEY depuis l'environnement, ou génère/persiste une clé aléatoire.

    Sécurité : aucune valeur par défaut fixe et connue n'est utilisée (une clé JWT
    connue permettrait de forger des sessions admin). Si SECRET_KEY n'est pas
    définie dans l'environnement, une clé aléatoire est générée une seule fois et
    stockée dans backend/.secret_key (fichier ignoré par git) afin de rester stable
    entre redémarrages sur une même instance.
    """
    env_key = os.getenv("SECRET_KEY", "").strip()
    if env_key:
        return env_key
    key_file = Path(__file__).resolve().parents[1] / ".secret_key"
    try:
        if key_file.exists():
            existing = key_file.read_text(encoding="utf-8").strip()
            if existing:
                return existing
        generated = secrets.token_hex(32)
        key_file.write_text(generated, encoding="utf-8")
        try:
            os.chmod(key_file, 0o600)
        except OSError:
            pass
        logger.warning(
            "SECRET_KEY absente de l'environnement : clé générée automatiquement et "
            "persistée dans %s. Définir SECRET_KEY dans backend/.env pour un déploiement "
            "reproductible ou multi-instance.", key_file,
        )
        return generated
    except OSError as exc:
        logger.warning(
            "Impossible d'écrire le fichier de clé secrète (%s) : clé éphémère utilisée, "
            "les sessions seront invalidées à chaque redémarrage.", exc,
        )
        return secrets.token_hex(32)


SECRET_KEY = _load_or_create_secret_key()
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("TOKEN_EXPIRE_MINUTES", "480"))

# Cookies de session marqués Secure (envoyés uniquement en HTTPS) — à activer dès
# que l'application est servie en HTTPS (Nginx/Synology avec certificat, ou tout
# reverse proxy TLS). Reste désactivé par défaut pour ne pas casser un accès
# local en http://localhost pendant le développement.
COOKIE_SECURE = os.getenv("COOKIE_SECURE", "false").strip().lower() in {"1", "true", "yes", "on"}

BCRYPT_ROUNDS = 12


PASSWORD_MIN_LENGTH = 10


def validate_password_strength(password: str, username: str | None = None) -> Optional[str]:
    """Vérifie la robustesse d'un mot de passe (création ou changement).

    Retourne un message d'erreur (str) si le mot de passe est trop faible,
    ou None s'il respecte la politique :
      - au moins 10 caractères,
      - au moins une lettre et un chiffre,
      - différent du nom d'utilisateur.
    """
    if len(password) < PASSWORD_MIN_LENGTH:
        return f"Le mot de passe doit contenir au moins {PASSWORD_MIN_LENGTH} caractères."
    if not re.search(r"[A-Za-z]", password):
        return "Le mot de passe doit contenir au moins une lettre."
    if not re.search(r"\d", password):
        return "Le mot de passe doit contenir au moins un chiffre."
    if username and password.lower() == username.lower():
        return "Le mot de passe ne doit pas être identique à l'identifiant."
    return None


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds=BCRYPT_ROUNDS)).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except (ValueError, TypeError):
        return False


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    to_encode.setdefault("typ", "staff")
    expire = datetime.now(timezone.utc) + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


# ── Double authentification (TOTP) — obligatoire pour le role admin ──────────
# Cookie temporaire distinct de la session (access_token) : porte uniquement
# l'identité en cours de vérification, jamais un accès à l'application. Un
# secret TOTP pas encore confirmé (enrôlement en cours) transite dans ce cookie
# plutôt qu'en base, pour ne jamais persister de secret 2FA non validé par le
# propriétaire du compte.
TWO_FA_PENDING_EXPIRE_MINUTES = 10


def create_2fa_pending_token(typ: str, username: str, secret: str | None = None) -> str:
    payload: dict = {"sub": username, "typ": typ}
    if secret:
        payload["secret"] = secret
    expire = datetime.now(timezone.utc) + timedelta(minutes=TWO_FA_PENDING_EXPIRE_MINUTES)
    payload["exp"] = expire
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def decode_2fa_pending_token(token: str, expected_typ: str) -> Optional[dict]:
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError:
        return None
    if payload.get("typ") != expected_typ:
        return None
    return payload


def generate_totp_secret() -> str:
    import pyotp
    return pyotp.random_base32()


def totp_provisioning_uri(username: str, secret: str) -> str:
    import pyotp
    return pyotp.TOTP(secret).provisioning_uri(name=username, issuer_name="Restor-PC RescueGrid")


def verify_totp_code(secret: str, code: str) -> bool:
    import pyotp
    code = (code or "").strip().replace(" ", "")
    if not code.isdigit():
        return False
    return pyotp.TOTP(secret).verify(code, valid_window=1)


def generate_recovery_codes(count: int = 8) -> list[str]:
    """Codes de secours a usage unique (perte du telephone/app TOTP), au format
    lisible XXXX-XXXX. Retournes en clair une seule fois a l'ecran ; seul leur
    hachage bcrypt est conserve (voir hash_recovery_codes)."""
    return [f"{secrets.token_hex(4)[:4]}-{secrets.token_hex(4)[:4]}".upper() for _ in range(count)]


def hash_recovery_codes(codes: list[str]) -> str:
    import json
    return json.dumps([hash_password(c) for c in codes])


def consume_recovery_code(user: User, code: str) -> bool:
    """Verifie un code de secours et le retire (usage unique) de la liste
    stockee sur l'utilisateur si valide. L'appelant doit committer la session
    apres appel pour que la consommation soit persistee."""
    import json
    if not user.totp_recovery_codes:
        return False
    code = (code or "").strip().upper()
    if not code:
        return False
    try:
        hashed_codes: list[str] = json.loads(user.totp_recovery_codes)
    except (ValueError, TypeError):
        return False
    for hashed in hashed_codes:
        if verify_password(code, hashed):
            hashed_codes.remove(hashed)
            user.totp_recovery_codes = json.dumps(hashed_codes)
            return True
    return False


def decode_token(token: str) -> Optional[dict]:
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError:
        return None
    # Empêche un cookie d'un autre espace (ex. client_token, typ="client") d'être
    # rejoué comme session staff même si un token venait à être intercepté/copié.
    if payload.get("typ") not in (None, "staff"):
        return None
    return payload


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
    user = session.scalars(select(User).where(User.username == username, User.is_active)).first()
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
    user = session.scalars(select(User).where(User.username == username, User.is_active)).first()
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
    admin_password = os.getenv("ADMIN_PASSWORD", "").strip()
    generated = False
    if not admin_password:
        # Sécurité : pas de mot de passe par défaut connu/documenté. Une valeur
        # aléatoire est générée à la première initialisation et affichée une seule
        # fois dans les logs — noter/changer ce mot de passe immédiatement.
        admin_password = secrets.token_urlsafe(12)
        generated = True
    admin = User(
        username="admin",
        hashed_password=hash_password(admin_password),
        full_name="Administrateur",
        role="admin",
        email="admin@rescuegrid.local",
    )
    session.add(admin)
    session.commit()
    if generated:
        logger.warning(
            "Aucun ADMIN_PASSWORD défini : mot de passe administrateur généré "
            "automatiquement -> %s (à noter immédiatement et à changer dans "
            "Paramètres après la première connexion).", admin_password,
        )
    else:
        logger.info("Compte administrateur par defaut cree : admin")

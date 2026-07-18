"""
main.py — Restor-PC RescueGrid v12.2
--------------------------------------
Point d'entrée FastAPI — réduit à l'essentiel.

Ce fichier contient uniquement :
  - La configuration de l'app (middlewares, static files, templates)
  - Les helpers partagés (sanitize, extract_zip, hardware, etc.)
  - Le dashboard (page principale)
  - Le démarrage (startup)
  - L'inclusion des routers modulaires

Routes déplacées dans app/routes/ :
  clients.py      → /clients, /client/{id}
  machines.py     → /machines, /machine/{id}
  interventions.py → /interventions, /intervention/{id}, /upload, /export
  billing.py      → /invoices, /quotes
  parts.py        → /parts
  tickets.py      → /tickets
  routes_v10.py   → /quotes PDF, /invoice PDF, /settings, /users, /activity, email SMTP
"""
from __future__ import annotations

import json
import logging
import os
import re
import shutil
import stat
from collections import defaultdict, deque
from datetime import datetime, timezone
from pathlib import Path
from zipfile import ZipFile

from urllib.parse import urlencode, urlparse

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import backup as backup_module
from . import reminders_scheduler
from . import stripe_payments
from .database import get_session, init_db, SessionLocal
from .helpers import apply_intervention_filters, generate_ai_summary, invoice_html, try_pdf_response
from .models import Client, Intervention, Invoice, Machine, Part, Quote, Ticket, User
from .routes_v10 import init_v10_routes
from .deps import get_client_ip, get_user_or_redirect
from .version import APP_VERSION

# ── Constantes ────────────────────────────────────────────────────────────────

BASE_DIR = Path(__file__).resolve().parents[1]
STORAGE_DIR = Path(os.getenv("STORAGE_PATH", str(BASE_DIR / "storage"))).resolve()
UPLOAD_DIR = STORAGE_DIR / "uploads"
REPORT_DIR = STORAGE_DIR / "reports"
MAX_UPLOAD_BYTES = int(os.getenv("MAX_UPLOAD_BYTES", str(2 * 1024 * 1024 * 1024)))
MAX_ZIP_FILES = int(os.getenv("MAX_ZIP_FILES", "10000"))
MAX_ZIP_UNCOMPRESSED_BYTES = int(os.getenv("MAX_ZIP_UNCOMPRESSED_BYTES", str(4 * 1024 * 1024 * 1024)))
STORAGE_DIR.mkdir(parents=True, exist_ok=True)
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
REPORT_DIR.mkdir(parents=True, exist_ok=True)

LOGIN_RATE_LIMIT_COUNT = int(os.getenv("LOGIN_RATE_LIMIT_COUNT", "5"))
LOGIN_RATE_LIMIT_WINDOW_SECONDS = int(os.getenv("LOGIN_RATE_LIMIT_WINDOW_SECONDS", "300"))
ACCOUNT_LOCKOUT_COUNT = int(os.getenv("ACCOUNT_LOCKOUT_COUNT", "5"))
ACCOUNT_LOCKOUT_WINDOW_SECONDS = int(os.getenv("ACCOUNT_LOCKOUT_WINDOW_SECONDS", "900"))
TWO_FA_ATTEMPT_COUNT = int(os.getenv("TWO_FA_ATTEMPT_COUNT", "8"))
TWO_FA_ATTEMPT_WINDOW_SECONDS = int(os.getenv("TWO_FA_ATTEMPT_WINDOW_SECONDS", "300"))


def _two_fa_rate_limited(username_key: str) -> bool:
    from .rate_limit import is_rate_limited
    return is_rate_limited(
        f"2fa:{username_key}",
        max_count=TWO_FA_ATTEMPT_COUNT,
        window_seconds=TWO_FA_ATTEMPT_WINDOW_SECONDS,
    )


def _record_two_fa_attempt(username_key: str) -> None:
    from .rate_limit import record_hit
    record_hit(f"2fa:{username_key}", window_seconds=TWO_FA_ATTEMPT_WINDOW_SECONDS)

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


# ── Helpers partagés ──────────────────────────────────────────────────────────

def sanitize_filename(value: str) -> str:
    cleaned = "".join(c if c.isalnum() or c in "-_." else "_" for c in value)
    return cleaned[:180] or "upload"


def _is_symlink_member(member) -> bool:
    """Détecte une entrée ZIP encodant un lien symbolique Unix (bit S_IFLNK dans
    external_attr, cf. format de zipfile sous Linux/macOS). Un tel lien peut
    pointer n'importe où sur le disque une fois extrait, même si son propre nom
    de chemin dans l'archive est valide — la validation de chemin ci-dessous ne
    suffit donc pas à elle seule à s'en protéger (variante de Zip Slip)."""
    mode = member.external_attr >> 16
    return bool(mode) and stat.S_ISLNK(mode)


def safe_extract_zip(archive_path: Path, destination: Path) -> None:
    destination = destination.resolve()
    total_size = 0
    with ZipFile(archive_path) as archive:
        members = archive.infolist()
        if len(members) > MAX_ZIP_FILES:
            raise HTTPException(status_code=413, detail=f"Archive trop volumineuse : {len(members)} fichiers")
        for member in members:
            if _is_symlink_member(member):
                raise HTTPException(status_code=400, detail="Archive ZIP invalide : lien symbolique refusé")
            total_size += max(member.file_size, 0)
            if total_size > MAX_ZIP_UNCOMPRESSED_BYTES:
                raise HTTPException(status_code=413, detail="Archive ZIP trop volumineuse après extraction")
            target_path = (destination / member.filename).resolve()
            if not target_path.is_relative_to(destination):
                raise HTTPException(status_code=400, detail="Archive ZIP invalide : chemin dangereux détecté")
        archive.extractall(destination)


def get_logo_path() -> str | None:
    config_path = BASE_DIR / "logo_config.json"
    if config_path.exists():
        try:
            configured = json.loads(config_path.read_text(encoding="utf-8")).get("logo_path")
            if configured:
                return configured
        except Exception as exc:
            logger.warning("Lecture logo_config impossible : %s", exc)
    default_logo = BASE_DIR / "static" / "restorpc_logo.png"
    return "/static/restorpc_logo.png" if default_logo.exists() else None


def risk_badge(level: str | None) -> dict:
    value = (level or "").lower()
    if any(w in value for w in ["critical", "critique", "noir", "urgent"]):
        return {"label": "Critique", "emoji": "⚫", "class": "risk-critical"}
    if any(w in value for w in ["high", "haut", "rouge", "danger"]):
        return {"label": "Élevé", "emoji": "🔴", "class": "risk-high"}
    if any(w in value for w in ["warning", "warn", "suspect", "orange", "moyen"]):
        return {"label": "Surveillance", "emoji": "🟠", "class": "risk-warning"}
    if value:
        return {"label": level, "emoji": "🟢", "class": "risk-ok"}
    return {"label": "Non évalué", "emoji": "⚪", "class": "risk-none"}


def _gb(value) -> str:
    try:
        return f"{float(value) / (1024 ** 3):.0f} Go"
    except (TypeError, ValueError):
        return "-"


def _tb(value) -> str:
    try:
        tb = float(value) / (1024 ** 4)
        return f"{tb:.2f} To"
    except (TypeError, ValueError):
        return "-"


def _as_list(value):
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, dict):
        return [value]
    return []


def _first_dict(*values):
    for value in values:
        if isinstance(value, dict) and value:
            return value
        if isinstance(value, list):
            for item in value:
                if isinstance(item, dict) and item:
                    return item
    return {}


def _pick(d, *keys):
    if not isinstance(d, dict):
        return None
    lowered = {str(k).lower(): v for k, v in d.items()}
    for key in keys:
        if key in d and d.get(key) not in (None, ""):
            return d.get(key)
        lk = str(key).lower()
        if lk in lowered and lowered[lk] not in (None, ""):
            return lowered[lk]
    return None


def _hardware_from_inventory(inv: dict) -> dict:
    machine = _first_dict(inv.get("machine"), inv.get("system"), inv.get("computer_system"), inv.get("os"))
    osinfo = _first_dict(inv.get("os"), inv.get("operating_system"), inv.get("windows"), inv.get("machine"))
    cpu = _first_dict(inv.get("processors"), inv.get("processor"), inv.get("cpu"))
    gpu = _first_dict(inv.get("video_controllers"), inv.get("video"), inv.get("gpu"), inv.get("graphics"))
    disks = _as_list(inv.get("disks") or inv.get("physical_disks") or inv.get("drives") or inv.get("storage"))

    cpu_name = _pick(cpu, "Name", "name", "ProcessorName", "Model") or "-"
    cores = _pick(cpu, "NumberOfCores", "Cores", "cores")
    threads = _pick(cpu, "NumberOfLogicalProcessors", "LogicalProcessors", "threads")
    cpu_sub = f"{cores or '-'} cœurs / {threads or '-'} threads" if cores or threads else ""

    ram_bytes = _pick(machine, "CsTotalPhysicalMemory", "TotalPhysicalMemory", "total_physical_memory")
    ram = _gb(ram_bytes) if ram_bytes else (_pick(machine, "RAM", "ram", "Memory") or "-")

    gpu_name = _pick(gpu, "Name", "name", "Caption", "Model") or "-"
    gpu_ram = _pick(gpu, "AdapterRAM", "Memory", "RAM")
    gpu_sub = _gb(gpu_ram) if gpu_ram else ""

    windows_name = (_pick(osinfo, "WindowsProductName", "Caption", "ProductName", "Name") or
                    _pick(machine, "WindowsProductName", "Caption", "ProductName") or "-")
    windows_version = _pick(osinfo, "WindowsVersion", "Version", "BuildNumber") or ""

    total = 0
    nvme_count = usb_count = ssd_count = hdd_count = 0
    for d in disks:
        if not isinstance(d, dict):
            continue
        size = _pick(d, "Size", "size", "TotalSize", "Bytes")
        try:
            total += int(float(size or 0))
        except (TypeError, ValueError):
            continue
        bus = str(_pick(d, "BusType", "bus", "InterfaceType") or "").lower()
        media = str(_pick(d, "MediaType", "type", "Model") or "").lower()
        if "nvme" in bus or "nvme" in media:
            nvme_count += 1
        if "usb" in bus:
            usb_count += 1
        if "ssd" in media or "nvme" in bus:
            ssd_count += 1
        if "hdd" in media:
            hdd_count += 1

    parts_list = []
    if nvme_count:
        parts_list.append(f"{nvme_count} NVMe")
    if ssd_count and not nvme_count:
        parts_list.append(f"{ssd_count} SSD")
    if hdd_count:
        parts_list.append(f"{hdd_count} HDD")
    if usb_count:
        parts_list.append(f"{usb_count} USB")

    return {
        "cpu": cpu_name, "cpu_sub": cpu_sub,
        "ram": ram, "ram_sub": "Mémoire installée" if ram and ram != "-" else "",
        "gpu": gpu_name, "gpu_sub": gpu_sub,
        "windows": str(windows_name).replace("Microsoft ", "") if windows_name else "-",
        "windows_sub": str(windows_version or ""),
        "storage": _tb(total) if total else "-",
        "storage_sub": " + ".join(parts_list),
    }


def _hardware_for_intervention(intervention: Intervention | None) -> dict:
    specs = {k: "-" for k in ["machine", "cpu", "ram", "gpu", "windows", "storage"]}
    specs.update({k: "" for k in ["cpu_sub", "ram_sub", "gpu_sub", "windows_sub", "storage_sub"]})
    if not intervention:
        return specs

    specs["machine"] = intervention.machine_name or (intervention.machine.machine_name if intervention.machine else "-")
    folder = intervention_dir(intervention)

    candidates: list[Path] = []
    if folder:
        candidates.append(folder / "inventory.json")

    for inv_path in candidates:
        if inv_path and inv_path.exists():
            try:
                inv = json.loads(inv_path.read_text(encoding="utf-8-sig", errors="replace"))
                specs.update({k: v for k, v in _hardware_from_inventory(inv).items() if v not in (None, "", "-")})
                break
            except Exception as exc:
                logger.warning("Lecture inventory impossible : %s", exc)
    return specs


def default_billing_amount(intervention: Intervention | None) -> float:
    if not intervention:
        return 60.0
    minutes = int(getattr(intervention, "labor_minutes", 0) or 0)
    rate = float(getattr(intervention, "labor_rate", 0) or 60.0)
    return round((minutes / 60.0) * rate, 2) if minutes > 0 else 60.0


def today_date() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def next_document_number(session: Session, prefix: str, model, field_name: str) -> str:
    """Délègue à helpers.next_document_number (source unique)."""
    from .helpers import next_document_number as _next
    return _next(session, prefix, model, field_name)


def allocate_document_number(session: Session, prefix: str, model, field_name: str, build_row, *, max_attempts: int = 8):
    """Délègue à helpers.allocate_document_number (source unique)."""
    from .helpers import allocate_document_number as _alloc
    return _alloc(session, prefix, model, field_name, build_row, max_attempts=max_attempts)


def intervention_url(intervention: Intervention) -> str:
    return f"/intervention/{intervention.id}"


def intervention_dir(intervention: Intervention) -> Path | None:
    if intervention.report_path:
        return (STORAGE_DIR / intervention.report_path).resolve().parent
    if intervention.archive_path:
        return REPORT_DIR / Path(intervention.archive_path).stem
    return None


def resolve_storage_path(relative_path: str) -> Path:
    storage_root = STORAGE_DIR.resolve()
    target = (STORAGE_DIR / relative_path).resolve()
    if not target.is_relative_to(storage_root):
        raise HTTPException(status_code=400, detail="Chemin invalide")
    return target


def build_dashboard_context(request, session, user, q=None, status=None, sort=None) -> dict:
    from sqlalchemy import func, or_

    if q:
        query = f"%{q}%"
        clients = session.scalars(select(Client).where(Client.name.ilike(query)).order_by(Client.created_at.desc()).limit(50)).all()
        machines = session.scalars(select(Machine).where(
            (Machine.machine_name.ilike(query)) | (Machine.bios_serial.ilike(query))
        ).order_by(Machine.last_intervention.desc().nulls_last()).limit(50)).all()
        interventions = session.scalars(select(Intervention).where(
            (Intervention.title.ilike(query)) | (Intervention.machine_name.ilike(query)) |
            (Intervention.bios_serial.ilike(query))
        ).order_by(Intervention.created_at.desc()).limit(50)).all()
        invoices = session.scalars(select(Invoice).where(Invoice.invoice_number.ilike(query)).order_by(Invoice.created_at.desc()).limit(50)).all()
        quotes = session.scalars(select(Quote).where(Quote.quote_number.ilike(query)).order_by(Quote.created_at.desc()).limit(50)).all()
        tickets = session.scalars(select(Ticket).where(
            (Ticket.title.ilike(query)) | (Ticket.status.ilike(query))
        ).order_by(Ticket.created_at.desc()).limit(50)).all()
        parts: list = []
        stats = {
            "clients": len(clients),
            "machines": len(machines),
            "interventions": len(interventions),
            "disk_critical": 0,
            "disk_warning": 0,
            "tickets_open": sum(1 for t in tickets if (t.status or "").lower() in {"open", "in_progress", "ouvert"}),
            "monthly_revenue": 0.0,
            "parts_stock": 0,
            "best_score": max([i.health_score for i in interventions if i.health_score is not None] or [0]),
        }
    else:
        # Listes affichées : limitées (pas toute la table).
        interventions = session.scalars(apply_intervention_filters(select(Intervention), status, sort).limit(100)).all()
        clients = session.scalars(select(Client).order_by(Client.created_at.desc()).limit(50)).all()
        machines = session.scalars(select(Machine).order_by(Machine.last_intervention.desc().nulls_last()).limit(50)).all()
        invoices = session.scalars(select(Invoice).order_by(Invoice.created_at.desc()).limit(50)).all()
        quotes = session.scalars(select(Quote).order_by(Quote.created_at.desc()).limit(50)).all()
        tickets = session.scalars(select(Ticket).order_by(Ticket.created_at.desc()).limit(50)).all()
        parts = session.scalars(select(Part).order_by(Part.created_at.desc()).limit(50)).all()

        # Stats globales en SQL (scalable à plusieurs milliers de lignes).
        now = datetime.now(timezone.utc)
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        critical_words = ("critical", "critique", "rouge", "noir", "urgent", "danger", "high")
        warning_words = ("warning", "suspect", "orange", "moyen", "surveillance")
        crit_filter = or_(*[
            Intervention.disk_risk.ilike(f"%{w}%") for w in critical_words
        ] + [
            Intervention.data_loss_risk.ilike(f"%{w}%") for w in critical_words
        ])
        warn_filter = or_(*[
            Intervention.disk_risk.ilike(f"%{w}%") for w in warning_words
        ] + [
            Intervention.data_loss_risk.ilike(f"%{w}%") for w in warning_words
        ])
        stats = {
            "clients": session.scalar(select(func.count()).select_from(Client)) or 0,
            "machines": session.scalar(select(func.count()).select_from(Machine)) or 0,
            "interventions": session.scalar(select(func.count()).select_from(Intervention)) or 0,
            "disk_critical": session.scalar(select(func.count()).select_from(Intervention).where(crit_filter)) or 0,
            "disk_warning": session.scalar(select(func.count()).select_from(Intervention).where(warn_filter)) or 0,
            "tickets_open": session.scalar(
                select(func.count()).select_from(Ticket).where(
                    Ticket.status.in_(["open", "in_progress", "ouvert"])
                )
            ) or 0,
            "monthly_revenue": float(
                session.scalar(
                    select(func.coalesce(func.sum(Invoice.total), 0)).where(
                        Invoice.created_at >= month_start,
                        Invoice.status.in_(["paid", "payée"]),
                    )
                ) or 0
            ),
            "parts_stock": session.scalar(
                select(func.coalesce(func.sum(Part.quantity), 0))
            ) or 0,
            "best_score": session.scalar(select(func.max(Intervention.health_score))) or 0,
        }

    critical_words = ("critical", "critique", "rouge", "noir", "urgent", "danger", "high")
    warning_words = ("warning", "suspect", "orange", "moyen", "surveillance")
    disk_critical = [i for i in interventions if any(w in ((i.disk_risk or "") + " " + (i.data_loss_risk or "")).lower() for w in critical_words)]
    disk_warning = [i for i in interventions if any(w in ((i.disk_risk or "") + " " + (i.data_loss_risk or "")).lower() for w in warning_words)]
    open_tickets = [t for t in tickets if (t.status or "").lower() in {"open", "in_progress", "ouvert"}]

    alerts = []
    for item in disk_critical[:8]:
        alerts.append({"level": "critical", "title": item.title, "message": f"Risque disque : {item.disk_risk or item.data_loss_risk}", "url": f"/intervention/{item.id}"})
    for item in disk_warning[:8]:
        alerts.append({"level": "warning", "title": item.title, "message": f"À surveiller : {item.disk_risk or item.data_loss_risk}", "url": f"/intervention/{item.id}"})
    for ticket in open_tickets[:6]:
        alerts.append({"level": "ticket", "title": ticket.title, "message": f"Ticket {ticket.priority} · {ticket.status}", "url": "/tickets"})

    return {
        "request": request, "user": user,
        "logo_path": get_logo_path(),
        "clients": clients, "interventions": interventions, "machines": machines,
        "parts": parts, "invoices": invoices, "quotes": quotes, "tickets": tickets,
        "stats": stats,
        "alerts": alerts[:12],
        "recent_interventions": interventions[:10],
        "recent_tickets": tickets[:8],
        "risk_machines": [m for m in machines if any(i.disk_risk and str(i.disk_risk).lower() not in {"healthy", "ok", "faible"} for i in m.interventions)][:10],
        "atelier_statuses": ["nouvelle", "en_attente", "en_cours", "termine", "livre", "facture"],
        "risk_badge": risk_badge,
        "search_query": q or "",
        "filter_status": status or "",
        "filter_sort": sort or "",
        "dashboard_specs": _hardware_for_intervention(interventions[0] if interventions else None),
    }


# ── App FastAPI ───────────────────────────────────────────────────────────────

logger.info("Démarrage Restor-PC RescueGrid v%s", APP_VERSION)

app = FastAPI(title="Restor-PC RescueGrid", version=APP_VERSION)
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
templates.env.globals["app_version"] = APP_VERSION


def pagination_query(request: Request, page: int) -> str:
    """Construit l'URL de la page courante avec un numéro de page différent,
    en conservant les autres filtres (q, status, sort...) déjà dans l'URL."""
    params = dict(request.query_params)
    params["page"] = str(page)
    return f"{request.url.path}?{urlencode(params)}"


templates.env.globals["pagination_query"] = pagination_query


def overdue_count() -> int:
    """Nombre de devis/factures en retard, affiché en badge sur la nav "Relances".

    Ouvre une session courte dédiée : les templates n'ont pas accès à la
    session de la requête en cours (pattern Jinja2Templates de FastAPI).
    """
    from .models import Invoice, Quote
    now = datetime.now(timezone.utc)
    try:
        with SessionLocal() as session:
            n_quotes = session.scalar(
                select(func.count()).select_from(Quote).where(
                    Quote.status == "sent", Quote.valid_until.is_not(None), Quote.valid_until < now
                )
            ) or 0
            n_invoices = session.scalar(
                select(func.count()).select_from(Invoice).where(
                    Invoice.status == "issued", Invoice.due_date.is_not(None), Invoice.due_date < now
                )
            ) or 0
            return int(n_quotes) + int(n_invoices)
    except Exception:
        logger.debug("Impossible de calculer overdue_count", exc_info=True)
        return 0


templates.env.globals["overdue_count"] = overdue_count


# ── Protection anti-CSRF (jeton + Origin/Referer) ─────────────────────────────
# Voir app/csrf.py : cookie double-submit + champ formulaire (ou en-tête
# X-CSRF-Token). /upload et /stripe/webhook restent exemptés.
from .csrf import CsrfProtectMiddleware, csrf_field_html

app.add_middleware(CsrfProtectMiddleware)
templates.env.globals["csrf_field"] = csrf_field_html


# ── En-têtes de sécurité HTTP ───────────────────────────────────────────────
# Durcissement de base (defense in depth) : empêche l'affichage du dashboard
# dans une <iframe> tierce (clickjacking), le sniffing de type MIME, et limite
# les fuites de referrer. HSTS n'est ajouté que si COOKIE_SECURE=true (HTTPS
# actif), sans quoi HSTS casserait un accès local en http://localhost.
@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "same-origin"
    response.headers.setdefault(
        "Content-Security-Policy",
        "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; "
        "script-src 'self' 'unsafe-inline'; frame-ancestors 'none'",
    )
    from .auth import COOKIE_SECURE
    if COOKIE_SECURE:
        response.headers["Strict-Transport-Security"] = "max-age=63072000; includeSubDomains"
    return response

# Routers modulaires
from .routes import clients as r_clients
from .routes import machines as r_machines
from .routes import interventions as r_interventions
from .routes import parts as r_parts
from .routes import tickets as r_tickets
from .routes import billing as r_billing
from .routes import planning as r_planning
from .routes import client_portal as r_client_portal

# r_client_portal est inclus AVANT r_clients : les routes littérales /client/login,
# /client/logout, /client/portal doivent être testées avant le pattern générique
# /client/{client_id} (clients.py), sinon Starlette matcherait "login"/"portal"
# comme un client_id et renverrait une erreur 422 (échec de conversion en int).
app.include_router(r_client_portal.init_router(templates))
app.include_router(r_clients.init_router(templates))
app.include_router(r_machines.init_router(templates, _hardware_for_intervention))
app.include_router(r_interventions.init_router(
    templates, STORAGE_DIR, REPORT_DIR, UPLOAD_DIR,
    sanitize_filename, intervention_dir, resolve_storage_path,
    safe_extract_zip, _hardware_for_intervention, default_billing_amount,
))
app.include_router(r_parts.init_router(templates))
app.include_router(r_tickets.init_router(templates))
app.include_router(r_billing.init_router(templates, next_document_number, default_billing_amount))
app.include_router(r_planning.init_router(templates))
app.include_router(init_v10_routes(
    templates, STORAGE_DIR, REPORT_DIR, sanitize_filename, intervention_dir, resolve_storage_path
))


# ── Démarrage ─────────────────────────────────────────────────────────────────

@app.on_event("startup")
async def on_startup() -> None:
    STORAGE_DIR.mkdir(exist_ok=True)
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    if os.getenv("ALLOW_ANONYMOUS_UPLOAD", "").strip().lower() in {"1", "true", "yes", "on"}:
        logger.warning(
            "ALLOW_ANONYMOUS_UPLOAD=true : /upload accepte des imports ZIP sans authentification "
            "ni clé API. À réserver à un usage local/dev sur réseau de confiance — "
            "ne jamais activer sur une instance exposée publiquement."
        )
    init_db()
    with SessionLocal() as session:
        from .auth import create_default_admin
        create_default_admin(session)
    # asyncio.create_task() nécessite une boucle en cours d'exécution : on ne peut
    # démarrer le scheduler que depuis un handler startup *async* (les handlers sync
    # sont exécutés dans un threadpool par Starlette, sans event loop courant).
    backup_module.start_backup_scheduler(BASE_DIR, STORAGE_DIR)
    reminders_scheduler.start_reminder_scheduler()


# ── Routes noyau ──────────────────────────────────────────────────────────────

@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request, "error": None})


@app.post("/login")
async def login_post(
    request: Request,
    session: Session = Depends(get_session),
):
    from .auth import authenticate_user, create_access_token
    from .rate_limit import clear_bucket, is_rate_limited, record_hit

    form = await request.form()
    username = str(form.get("username", "")).strip()
    password = str(form.get("password", ""))
    client_ip = get_client_ip(request)
    username_key = username.lower()
    ip_bucket = f"login_ip:{client_ip}"
    acct_bucket = f"login_user:{username_key}"

    if is_rate_limited(ip_bucket, max_count=LOGIN_RATE_LIMIT_COUNT, window_seconds=LOGIN_RATE_LIMIT_WINDOW_SECONDS):
        logger.warning("Rate limit login dépassé pour IP %s", client_ip)
        return templates.TemplateResponse("login.html", {"request": request, "error": "Trop de tentatives. Réessayez dans 5 minutes."}, status_code=429)

    if username_key and is_rate_limited(
        acct_bucket, max_count=ACCOUNT_LOCKOUT_COUNT, window_seconds=ACCOUNT_LOCKOUT_WINDOW_SECONDS
    ):
        logger.warning("Compte verrouillé temporairement après échecs répétés : %s", username)
        return templates.TemplateResponse(
            "login.html",
            {"request": request, "error": "Compte temporairement verrouillé suite à plusieurs échecs. Réessayez dans quelques minutes."},
            status_code=429,
        )

    user = authenticate_user(username, password, session)
    if not user:
        record_hit(ip_bucket, window_seconds=LOGIN_RATE_LIMIT_WINDOW_SECONDS)
        if username_key:
            record_hit(acct_bucket, window_seconds=ACCOUNT_LOCKOUT_WINDOW_SECONDS)
        logger.warning("Échec connexion pour %s depuis %s", username, client_ip)
        return templates.TemplateResponse("login.html", {"request": request, "error": "Identifiant ou mot de passe incorrect."})

    clear_bucket(ip_bucket)
    clear_bucket(acct_bucket)
    logger.info("Mot de passe validé : %s depuis %s", username, client_ip)
    from .auth import COOKIE_SECURE, create_2fa_pending_token

    # 2FA obligatoire pour le rôle admin uniquement (voir routes /2fa/*
    # ci-dessous) : le mot de passe seul ne suffit jamais à ouvrir une session
    # pour ce rôle, qu'il soit déjà enrôlé (redirection vers /2fa/verify) ou
    # pas encore (enrôlement forcé via /2fa/setup avant tout accès).
    if user.role == "admin":
        typ = "staff_2fa_verify" if user.totp_enabled else "staff_2fa_setup"
        pending = create_2fa_pending_token(typ, user.username)
        response = RedirectResponse("/2fa/verify" if user.totp_enabled else "/2fa/setup", status_code=303)
        response.set_cookie("pending_2fa", pending, httponly=True, samesite="lax", secure=COOKIE_SECURE)
        return response

    token = create_access_token({"sub": user.username})
    response = RedirectResponse("/", status_code=303)
    response.set_cookie("access_token", token, httponly=True, samesite="lax", secure=COOKIE_SECURE)
    return response


@app.get("/logout")
def logout():
    response = RedirectResponse("/login", status_code=303)
    response.delete_cookie("access_token")
    response.delete_cookie("pending_2fa")
    return response


def _finalize_login(username: str) -> RedirectResponse:
    from .auth import COOKIE_SECURE, create_access_token
    token = create_access_token({"sub": username})
    response = RedirectResponse("/", status_code=303)
    response.set_cookie("access_token", token, httponly=True, samesite="lax", secure=COOKIE_SECURE)
    response.delete_cookie("pending_2fa")
    return response


@app.get("/2fa/setup", response_class=HTMLResponse)
def two_fa_setup_page(request: Request, session: Session = Depends(get_session)):
    from .auth import decode_2fa_pending_token, generate_totp_secret, totp_provisioning_uri

    pending_token = request.cookies.get("pending_2fa", "")
    payload = decode_2fa_pending_token(pending_token, "staff_2fa_setup")
    if not payload:
        return RedirectResponse("/login", status_code=303)
    username = payload["sub"]
    secret = payload.get("secret") or generate_totp_secret()

    # Génère le secret une seule fois pour cet enrôlement puis le fige dans le
    # cookie temporaire (jamais en base tant que le code n'est pas confirmé) —
    # sans quoi rafraîchir la page changerait le QR code affiché à chaque fois.
    if not payload.get("secret"):
        from .auth import create_2fa_pending_token
        new_pending = create_2fa_pending_token("staff_2fa_setup", username, secret=secret)
    else:
        new_pending = pending_token

    qr_data_uri = _totp_qr_data_uri(totp_provisioning_uri(username, secret))
    response = templates.TemplateResponse(
        "2fa_setup.html",
        {"request": request, "secret": secret, "qr_data_uri": qr_data_uri, "error": None},
    )
    from .auth import COOKIE_SECURE
    response.set_cookie("pending_2fa", new_pending, httponly=True, samesite="lax", secure=COOKIE_SECURE)
    return response


def _totp_qr_data_uri(uri: str) -> str:
    import base64
    import io
    import qrcode

    img = qrcode.make(uri)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode("ascii")


@app.post("/2fa/setup", response_class=HTMLResponse)
async def two_fa_setup_confirm(request: Request, session: Session = Depends(get_session)):
    from .auth import (
        decode_2fa_pending_token, generate_recovery_codes, hash_recovery_codes,
        log_activity, totp_provisioning_uri, verify_totp_code,
    )

    pending_token = request.cookies.get("pending_2fa", "")
    payload = decode_2fa_pending_token(pending_token, "staff_2fa_setup")
    if not payload or not payload.get("secret"):
        return RedirectResponse("/login", status_code=303)
    username = payload["sub"]
    secret = payload["secret"]

    if _two_fa_rate_limited(username.lower()):
        return templates.TemplateResponse(
            "2fa_setup.html",
            {"request": request, "secret": secret, "qr_data_uri": _totp_qr_data_uri(totp_provisioning_uri(username, secret)),
             "error": "Trop de tentatives. Réessayez dans quelques minutes."},
            status_code=429,
        )

    form = await request.form()
    code = str(form.get("code", ""))
    if not verify_totp_code(secret, code):
        _record_two_fa_attempt(username.lower())
        return templates.TemplateResponse(
            "2fa_setup.html",
            {"request": request, "secret": secret, "qr_data_uri": _totp_qr_data_uri(totp_provisioning_uri(username, secret)),
             "error": "Code invalide — vérifiez l'heure de votre téléphone et réessayez."},
        )

    user = session.scalars(select(User).where(User.username == username)).first()
    if not user:
        return RedirectResponse("/login", status_code=303)
    recovery_codes = generate_recovery_codes()
    user.totp_secret = secret
    user.totp_enabled = True
    user.totp_recovery_codes = hash_recovery_codes(recovery_codes)
    log_activity(session, user, "2fa.enable")
    session.commit()

    return templates.TemplateResponse(
        "2fa_recovery_codes.html",
        {"request": request, "recovery_codes": recovery_codes},
    )


@app.post("/2fa/setup/continue")
def two_fa_setup_continue(request: Request):
    """Après affichage unique des codes de secours (2fa_recovery_codes.html),
    ouvre enfin la session — voir _finalize_login."""
    from .auth import decode_token
    token = request.cookies.get("access_token", "")
    payload = decode_token(token) if token else None
    if payload:
        return RedirectResponse("/", status_code=303)
    pending = request.cookies.get("pending_2fa", "")
    from .auth import decode_2fa_pending_token
    payload = decode_2fa_pending_token(pending, "staff_2fa_setup")
    if not payload:
        return RedirectResponse("/login", status_code=303)
    return _finalize_login(payload["sub"])


@app.get("/2fa/verify", response_class=HTMLResponse)
def two_fa_verify_page(request: Request):
    from .auth import decode_2fa_pending_token
    payload = decode_2fa_pending_token(request.cookies.get("pending_2fa", ""), "staff_2fa_verify")
    if not payload:
        return RedirectResponse("/login", status_code=303)
    return templates.TemplateResponse("2fa_verify.html", {"request": request, "error": None})


@app.post("/2fa/verify", response_class=HTMLResponse)
async def two_fa_verify_confirm(request: Request, session: Session = Depends(get_session)):
    from .auth import consume_recovery_code, decode_2fa_pending_token, log_activity, verify_totp_code

    payload = decode_2fa_pending_token(request.cookies.get("pending_2fa", ""), "staff_2fa_verify")
    if not payload:
        return RedirectResponse("/login", status_code=303)
    username = payload["sub"]
    username_key = username.lower()

    if _two_fa_rate_limited(username_key):
        return templates.TemplateResponse(
            "2fa_verify.html",
            {"request": request, "error": "Trop de tentatives. Réessayez dans quelques minutes."},
            status_code=429,
        )

    user = session.scalars(select(User).where(User.username == username)).first()
    if not user or not user.totp_enabled or not user.totp_secret:
        return RedirectResponse("/login", status_code=303)

    form = await request.form()
    code = str(form.get("code", ""))
    valid = verify_totp_code(user.totp_secret, code)
    if not valid and consume_recovery_code(user, code):
        valid = True
        log_activity(session, user, "2fa.recovery_code_used")
        session.commit()
        logger.warning("Code de secours 2FA utilisé pour le compte %s", username)

    if not valid:
        _record_two_fa_attempt(username_key)
        logger.warning("Code 2FA invalide pour %s", username)
        return templates.TemplateResponse(
            "2fa_verify.html", {"request": request, "error": "Code invalide."},
        )

    from .rate_limit import clear_bucket
    clear_bucket(f"2fa:{username_key}")
    logger.info("Connexion 2FA réussie : %s", username)
    return _finalize_login(username)


@app.get("/", response_class=HTMLResponse)
def dashboard(
    request: Request,
    status: str = "",
    sort: str = "",
    session: Session = Depends(get_session),
):
    from .auth import get_current_user
    user = get_current_user(request, session)
    if not user:
        return RedirectResponse("/login", status_code=303)
    return templates.TemplateResponse(
        "dashboard.html",
        build_dashboard_context(request, session, user, status=status or None, sort=sort or None),
    )


@app.get("/search")
def search(request: Request, q: str = "", session: Session = Depends(get_session)):
    from .auth import get_current_user
    user = get_current_user(request, session)
    if not user:
        return RedirectResponse("/login", status_code=303)
    return templates.TemplateResponse(
        "dashboard.html",
        build_dashboard_context(request, session, user, q=q.strip()),
    )


@app.get("/tools", response_class=HTMLResponse)
def tools_page(request: Request, session: Session = Depends(get_session)):
    user, redirect = get_user_or_redirect(request, session)
    if redirect:
        return redirect
    return templates.TemplateResponse("tools.html", {"request": request, "user": user, "active_page": "tools"})


@app.get("/api/stats")
def api_stats(request: Request, session: Session = Depends(get_session)):
    from .auth import get_current_user
    user = get_current_user(request, session)
    if not user:
        raise HTTPException(status_code=401, detail="Non autorisé")
    ctx = build_dashboard_context(request, session, user)
    return {"stats": ctx["stats"], "alerts": ctx["alerts"]}


@app.get("/health")
def healthcheck():
    return {"status": "ok", "version": APP_VERSION}


MAX_LOGO_BYTES = int(os.getenv("MAX_LOGO_BYTES", str(5 * 1024 * 1024)))


@app.post("/upload-logo")
async def upload_logo(request: Request, file: UploadFile = File(...), session: Session = Depends(get_session)):
    # Réservé à l'admin : ce logo apparaît sur tous les devis/factures envoyés
    # aux clients, un technicien standard ne doit pas pouvoir le remplacer.
    from .auth import get_admin_or_redirect
    user, redirect = get_admin_or_redirect(request, session)
    if redirect:
        return redirect
    if not file.content_type or not file.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="Fichier image requis")
    content = await file.read(MAX_LOGO_BYTES + 1)
    if len(content) > MAX_LOGO_BYTES:
        raise HTTPException(status_code=413, detail="Image trop volumineuse")
    logo_dir = STORAGE_DIR / "logos"
    logo_dir.mkdir(exist_ok=True)
    logo_path = logo_dir / "logo.png"
    logo_path.write_bytes(content)
    config_path = BASE_DIR / "logo_config.json"
    config_path.write_text(json.dumps({"logo_path": "logos/logo.png"}), encoding="utf-8")
    return RedirectResponse("/", status_code=303)


@app.get("/backup/database")
def backup_database(request: Request):
    # Réservé à l'admin : ce fichier contient l'intégralité de la base (clients,
    # mots de passe hashés, factures) — un compte technicien ne doit pas pouvoir
    # l'exfiltrer en un clic (voir /backup/history, réservé admin, pour comparaison).
    from .auth import get_admin_or_redirect
    with SessionLocal() as session:
        user, redirect = get_admin_or_redirect(request, session)
        if redirect:
            raise HTTPException(status_code=401, detail="Accès administrateur requis")
    for db_name in ["rescuegrid.db", "app.db"]:
        db_path = BASE_DIR / db_name
        if db_path.exists():
            def iterfile():
                with open(db_path, "rb") as f:
                    yield from f
            return StreamingResponse(iterfile(), media_type="application/octet-stream",
                                     headers={"Content-Disposition": "attachment; filename=rescuegrid_backup.db"})
    raise HTTPException(status_code=404, detail="Base SQLite introuvable")


@app.get("/backup/history", response_class=HTMLResponse)
def backup_history(request: Request, session: Session = Depends(get_session)):
    from .auth import get_admin_or_redirect
    user, redirect = get_admin_or_redirect(request, session)
    if redirect:
        return redirect
    backups = backup_module.list_backups(STORAGE_DIR)
    return templates.TemplateResponse(
        "tools.html",
        {
            "request": request,
            "user": user,
            "active_page": "tools",
            "backups": backups,
            "backup_retention": backup_module.BACKUP_RETENTION_COUNT,
            "backup_schedule_hour": backup_module.BACKUP_SCHEDULE_HOUR,
            "backup_schedule_enabled": backup_module.BACKUP_SCHEDULE_ENABLED,
            "backup_is_postgres": backup_module.is_postgres(),
        },
    )


@app.post("/backup/run")
def backup_run(request: Request, session: Session = Depends(get_session)):
    from .auth import get_admin_or_redirect
    user, redirect = get_admin_or_redirect(request, session)
    if redirect:
        return redirect
    try:
        backup_module.perform_backup_and_rotate(BASE_DIR, STORAGE_DIR)
    except Exception as exc:
        logger.exception("Sauvegarde manuelle échouée")
        return RedirectResponse(f"/backup/history?{urlencode({'error': str(exc)})}", status_code=303)
    return RedirectResponse("/backup/history?ok=1", status_code=303)


@app.get("/backup/download/{filename}")
def backup_download(filename: str, request: Request, session: Session = Depends(get_session)):
    from .auth import get_admin_or_redirect
    _, redirect = get_admin_or_redirect(request, session)
    if redirect:
        return redirect
    safe_name = Path(filename).name
    if not safe_name.startswith("rescuegrid_") or safe_name != filename:
        raise HTTPException(status_code=400, detail="Nom de fichier invalide")
    target = (STORAGE_DIR / "backups" / safe_name).resolve()
    backups_dir = (STORAGE_DIR / "backups").resolve()
    if not target.is_relative_to(backups_dir) or not target.exists():
        raise HTTPException(status_code=404, detail="Sauvegarde introuvable")

    def iterfile():
        with open(target, "rb") as f:
            yield from f
    return StreamingResponse(iterfile(), media_type="application/octet-stream",
                             headers={"Content-Disposition": f"attachment; filename={safe_name}"})


@app.get("/storage/{file_path:path}")
def serve_storage_file(file_path: str, request: Request, session: Session = Depends(get_session)):
    user, redirect = get_user_or_redirect(request, session)
    if redirect:
        return redirect
    target = resolve_storage_path(file_path)
    if not target.is_file():
        raise HTTPException(status_code=404, detail="Fichier introuvable")
    return FileResponse(target)


@app.get("/invoice/{invoice_id}/pdf", response_class=HTMLResponse)
def invoice_pdf(invoice_id: int, request: Request, session: Session = Depends(get_session)):
    user, redirect = get_user_or_redirect(request, session)
    if redirect:
        return redirect
    invoice = session.scalars(select(Invoice).where(Invoice.id == invoice_id)).first()
    if not invoice:
        raise HTTPException(status_code=404, detail="Facture introuvable")
    stripe_payments.ensure_payment_link(session, invoice)
    return try_pdf_response(invoice_html(invoice), f"{invoice.invoice_number}.pdf")


# ── Paiement en ligne (Stripe) ─────────────────────────────────────────────────

@app.post("/invoice/{invoice_id}/payment-link")
def create_invoice_payment_link(invoice_id: int, request: Request, session: Session = Depends(get_session)):
    """Génère (ou renouvelle) le lien de paiement Stripe d'une facture et
    redirige vers la liste des factures avec l'URL en query string, affichée
    par le template (bouton copier-coller) — voir templates/invoices.html."""
    user, redirect = get_user_or_redirect(request, session)
    if redirect:
        return redirect
    invoice = session.scalars(select(Invoice).where(Invoice.id == invoice_id)).first()
    if not invoice:
        raise HTTPException(status_code=404, detail="Facture introuvable")
    if not stripe_payments.stripe_enabled():
        return RedirectResponse("/invoices?payment_link_error=stripe_not_configured", status_code=303)
    link = stripe_payments.ensure_payment_link(session, invoice)
    if not link:
        return RedirectResponse("/invoices?payment_link_error=creation_failed", status_code=303)
    params = urlencode({"payment_link_id": invoice.id, "payment_link_url": link})
    return RedirectResponse(f"/invoices?{params}", status_code=303)


@app.post("/stripe/webhook")
async def stripe_webhook(request: Request, session: Session = Depends(get_session)):
    """Point d'entrée serveur à serveur appelé par Stripe (pas de session
    navigateur) : la vérification de la signature `Stripe-Signature` tient
    lieu d'authentification. Voir stripe_payments.verify_and_handle_webhook."""
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature", "")
    ok = stripe_payments.verify_and_handle_webhook(payload, sig_header, session)
    if not ok:
        raise HTTPException(status_code=400, detail="Signature webhook invalide")
    return JSONResponse({"received": True})


@app.get("/pay/success", response_class=HTMLResponse)
def pay_success(request: Request, invoice: str | None = None):
    return templates.TemplateResponse("pay_success.html", {"request": request, "invoice_number": invoice})


@app.get("/pay/cancel", response_class=HTMLResponse)
def pay_cancel(request: Request, invoice: str | None = None):
    return templates.TemplateResponse("pay_cancel.html", {"request": request, "invoice_number": invoice})

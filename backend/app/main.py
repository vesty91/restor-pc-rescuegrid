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

from .database import get_session, init_db, SessionLocal
from .helpers import apply_intervention_filters, generate_ai_summary, invoice_html, try_pdf_response
from .models import Client, Intervention, Invoice, Machine, Part, Quote, Ticket, User
from .routes_v10 import init_v10_routes
from .deps import get_user_or_redirect

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

LOGIN_ATTEMPTS: dict[str, deque[float]] = defaultdict(deque)
LOGIN_RATE_LIMIT_COUNT = int(os.getenv("LOGIN_RATE_LIMIT_COUNT", "5"))
LOGIN_RATE_LIMIT_WINDOW_SECONDS = int(os.getenv("LOGIN_RATE_LIMIT_WINDOW_SECONDS", "300"))

# Verrouillage de compte par nom d'utilisateur — en complément du rate limit par IP
# ci-dessus. Une attaque par brute force distribuée (plusieurs IP, même compte) n'est
# pas freinée par le seul rate limit IP : ce second compteur, indexé par identifiant,
# verrouille le compte visé quelle que soit l'origine des tentatives.
ACCOUNT_LOCKOUT_ATTEMPTS: dict[str, deque[float]] = defaultdict(deque)
ACCOUNT_LOCKOUT_COUNT = int(os.getenv("ACCOUNT_LOCKOUT_COUNT", "5"))
ACCOUNT_LOCKOUT_WINDOW_SECONDS = int(os.getenv("ACCOUNT_LOCKOUT_WINDOW_SECONDS", "900"))

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


# ── Helpers partagés ──────────────────────────────────────────────────────────

def sanitize_filename(value: str) -> str:
    cleaned = "".join(c if c.isalnum() or c in "-_." else "_" for c in value)
    return cleaned[:180] or "upload"


def safe_extract_zip(archive_path: Path, destination: Path) -> None:
    destination = destination.resolve()
    total_size = 0
    with ZipFile(archive_path) as archive:
        members = archive.infolist()
        if len(members) > MAX_ZIP_FILES:
            raise HTTPException(status_code=413, detail=f"Archive trop volumineuse : {len(members)} fichiers")
        for member in members:
            total_size += max(member.file_size, 0)
            if total_size > MAX_ZIP_UNCOMPRESSED_BYTES:
                raise HTTPException(status_code=413, detail="Archive ZIP trop volumineuse après extraction")
            target_path = (destination / member.filename).resolve()
            if not str(target_path).startswith(str(destination)):
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
    except Exception:
        return "-"


def _tb(value) -> str:
    try:
        tb = float(value) / (1024 ** 4)
        return f"{tb:.2f} To"
    except Exception:
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
        except Exception:
            pass
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
    today = datetime.now(timezone.utc).strftime("%Y%m%d")
    pattern = f"{prefix}-{today}-%"
    field = getattr(model, field_name)
    existing = session.scalars(select(field).where(field.like(pattern))).all()
    max_index = 0
    for number in existing:
        match = re.match(rf"^{prefix}-{today}-(\d{{4,}})$", str(number or ""))
        if match:
            max_index = max(max_index, int(match.group(1)))
    return f"{prefix}-{today}-{max_index + 1:04d}"


def intervention_url(intervention: Intervention) -> str:
    return f"/intervention/{intervention.id}"


def intervention_dir(intervention: Intervention) -> Path | None:
    if intervention.report_path:
        return (STORAGE_DIR / intervention.report_path).resolve().parent
    if intervention.archive_path:
        return REPORT_DIR / Path(intervention.archive_path).stem
    return None


def resolve_storage_path(relative_path: str) -> Path:
    target = (STORAGE_DIR / relative_path).resolve()
    if not str(target).startswith(str(STORAGE_DIR.resolve())):
        raise HTTPException(status_code=400, detail="Chemin invalide")
    return target


def build_dashboard_context(request, session, user, q=None, status=None, sort=None) -> dict:
    if q:
        query = f"%{q}%"
        clients = session.scalars(select(Client).where(Client.name.ilike(query)).order_by(Client.created_at.desc())).all()
        machines = session.scalars(select(Machine).where(
            (Machine.machine_name.ilike(query)) | (Machine.bios_serial.ilike(query))
        ).order_by(Machine.last_intervention.desc().nulls_last())).all()
        interventions = session.scalars(select(Intervention).where(
            (Intervention.title.ilike(query)) | (Intervention.machine_name.ilike(query)) |
            (Intervention.bios_serial.ilike(query))
        ).order_by(Intervention.created_at.desc())).all()
        invoices = session.scalars(select(Invoice).where(Invoice.invoice_number.ilike(query)).order_by(Invoice.created_at.desc())).all()
        quotes = session.scalars(select(Quote).where(Quote.quote_number.ilike(query)).order_by(Quote.created_at.desc())).all()
        tickets = session.scalars(select(Ticket).where(
            (Ticket.title.ilike(query)) | (Ticket.status.ilike(query))
        ).order_by(Ticket.created_at.desc())).all()
        parts = []
    else:
        clients = session.scalars(select(Client).order_by(Client.created_at.desc())).all()
        interventions = session.scalars(apply_intervention_filters(select(Intervention), status, sort)).all()
        machines = session.scalars(select(Machine).order_by(Machine.last_intervention.desc().nulls_last())).all()
        invoices = session.scalars(select(Invoice).order_by(Invoice.created_at.desc())).all()
        quotes = session.scalars(select(Quote).order_by(Quote.created_at.desc())).all()
        tickets = session.scalars(select(Ticket).order_by(Ticket.created_at.desc())).all()
        parts = session.scalars(select(Part).order_by(Part.created_at.desc())).all()

    critical_words = ("critical", "critique", "rouge", "noir", "urgent", "danger", "high")
    warning_words = ("warning", "suspect", "orange", "moyen", "surveillance")
    disk_critical = [i for i in interventions if any(w in ((i.disk_risk or "") + " " + (i.data_loss_risk or "")).lower() for w in critical_words)]
    disk_warning = [i for i in interventions if any(w in ((i.disk_risk or "") + " " + (i.data_loss_risk or "")).lower() for w in warning_words)]
    open_tickets = [t for t in tickets if (t.status or "").lower() in {"open", "in_progress", "ouvert"}]
    now = datetime.now(timezone.utc)
    month_invoices = [i for i in invoices if i.created_at.year == now.year and i.created_at.month == now.month and (i.status or "").lower() in {"paid", "payée"}]
    monthly_revenue = sum(float(i.total or 0) for i in month_invoices)

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
        "stats": {
            "clients": len(clients), "machines": len(machines), "interventions": len(interventions),
            "disk_critical": len(disk_critical), "disk_warning": len(disk_warning),
            "tickets_open": len(open_tickets), "monthly_revenue": monthly_revenue,
            "parts_stock": sum(max(p.quantity or 0, 0) for p in parts),
            "best_score": max([i.health_score for i in interventions if i.health_score is not None] or [0]),
        },
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

logger.info("Démarrage Restor-PC RescueGrid v12.2")

app = FastAPI(title="Restor-PC RescueGrid")
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


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
        return 0


templates.env.globals["overdue_count"] = overdue_count


# ── Protection anti-CSRF (vérification d'origine) ──────────────────────────────
# L'authentification repose sur un cookie de session (JWT). Pour les requêtes de
# mutation (POST/PUT/PATCH/DELETE) envoyées par un navigateur, on vérifie que
# l'en-tête Origin (ou Referer en repli) correspond bien à l'hôte de l'application.
# Une requête forgée depuis un autre site enverrait un Origin/Referer différent
# et est donc rejetée, même si le cookie de session est automatiquement joint.
#
# /upload est exclu : il est appelé par l'agent Windows (script, pas un navigateur),
# qui n'envoie ni Origin ni Referer, et dispose de sa propre protection
# (authentification par session ou UPLOAD_API_KEY, voir verify_upload_access).
CSRF_UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
CSRF_EXEMPT_PATHS = {"/upload"}


@app.middleware("http")
async def csrf_origin_guard(request: Request, call_next):
    if request.method in CSRF_UNSAFE_METHODS and request.url.path not in CSRF_EXEMPT_PATHS:
        source = request.headers.get("origin") or request.headers.get("referer")
        if source:
            source_host = urlparse(source).netloc
            expected_host = request.headers.get("host", "")
            if source_host and source_host != expected_host:
                logger.warning(
                    "Requête bloquée (origine invalide) : origin/referer=%s hôte attendu=%s chemin=%s",
                    source_host, expected_host, request.url.path,
                )
                return JSONResponse(
                    {"detail": "Requête refusée : origine invalide (protection anti-CSRF)."},
                    status_code=403,
                )
    return await call_next(request)

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
def on_startup() -> None:
    STORAGE_DIR.mkdir(exist_ok=True)
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    init_db()
    with SessionLocal() as session:
        from .auth import create_default_admin
        create_default_admin(session)


# ── Routes noyau ──────────────────────────────────────────────────────────────

@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request, "error": None})


@app.post("/login")
async def login_post(
    request: Request,
    session: Session = Depends(get_session),
):
    import time
    from .auth import authenticate_user, create_access_token
    form = await request.form()
    username = str(form.get("username", "")).strip()
    password = str(form.get("password", ""))
    client_ip = request.client.host if request.client else "unknown"

    now = time.time()
    attempts = LOGIN_ATTEMPTS[client_ip]
    while attempts and now - attempts[0] > LOGIN_RATE_LIMIT_WINDOW_SECONDS:
        attempts.popleft()
    if len(attempts) >= LOGIN_RATE_LIMIT_COUNT:
        logger.warning("Rate limit login dépassé pour IP %s", client_ip)
        return templates.TemplateResponse("login.html", {"request": request, "error": "Trop de tentatives. Réessayez dans 5 minutes."}, status_code=429)

    username_key = username.lower()
    account_attempts = ACCOUNT_LOCKOUT_ATTEMPTS[username_key]
    while account_attempts and now - account_attempts[0] > ACCOUNT_LOCKOUT_WINDOW_SECONDS:
        account_attempts.popleft()
    if username_key and len(account_attempts) >= ACCOUNT_LOCKOUT_COUNT:
        logger.warning("Compte verrouillé temporairement après échecs répétés : %s", username)
        return templates.TemplateResponse(
            "login.html",
            {"request": request, "error": "Compte temporairement verrouillé suite à plusieurs échecs. Réessayez dans quelques minutes."},
            status_code=429,
        )

    user = authenticate_user(username, password, session)
    if not user:
        attempts.append(now)
        if username_key:
            account_attempts.append(now)
        logger.warning("Échec connexion pour %s depuis %s", username, client_ip)
        return templates.TemplateResponse("login.html", {"request": request, "error": "Identifiant ou mot de passe incorrect."})

    LOGIN_ATTEMPTS.pop(client_ip, None)
    ACCOUNT_LOCKOUT_ATTEMPTS.pop(username_key, None)
    logger.info("Connexion réussie : %s depuis %s", username, client_ip)
    token = create_access_token({"sub": user.username})
    response = RedirectResponse("/", status_code=303)
    response.set_cookie("access_token", token, httponly=True, samesite="lax")
    return response


@app.get("/logout")
def logout():
    response = RedirectResponse("/login", status_code=303)
    response.delete_cookie("access_token")
    return response


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
    return {"status": "ok", "version": "12.2"}


@app.post("/upload-logo")
async def upload_logo(request: Request, file: UploadFile = File(...), session: Session = Depends(get_session)):
    user, redirect = get_user_or_redirect(request, session)
    if redirect:
        return redirect
    if not file.content_type or not file.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="Fichier image requis")
    logo_dir = STORAGE_DIR / "logos"
    logo_dir.mkdir(exist_ok=True)
    logo_path = logo_dir / "logo.png"
    with logo_path.open("wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
    config_path = BASE_DIR / "logo_config.json"
    config_path.write_text(json.dumps({"logo_path": "logos/logo.png"}), encoding="utf-8")
    return RedirectResponse("/", status_code=303)


@app.get("/backup/database")
def backup_database(request: Request):
    from .auth import get_current_user
    with SessionLocal() as session:
        user = get_current_user(request, session)
        if not user:
            raise HTTPException(status_code=401, detail="Non autorisé")
    for db_name in ["rescuegrid.db", "app.db"]:
        db_path = BASE_DIR / db_name
        if db_path.exists():
            def iterfile():
                with open(db_path, "rb") as f:
                    yield from f
            return StreamingResponse(iterfile(), media_type="application/octet-stream",
                                     headers={"Content-Disposition": "attachment; filename=rescuegrid_backup.db"})
    raise HTTPException(status_code=404, detail="Base SQLite introuvable")


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
    return try_pdf_response(invoice_html(invoice), f"{invoice.invoice_number}.pdf")

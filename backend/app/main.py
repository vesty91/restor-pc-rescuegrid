import json
import os
import shutil
from datetime import datetime
from pathlib import Path
from zipfile import ZipFile

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from openpyxl import Workbook
from sqlalchemy import select
from sqlalchemy.orm import Session

from .database import get_session, init_db, SessionLocal
from .models import Client, Intervention, Invoice, Machine, Part, Ticket, User


BASE_DIR = Path(__file__).resolve().parents[1]
STORAGE_DIR = Path(os.getenv("STORAGE_PATH", str(BASE_DIR / "storage"))).resolve()
UPLOAD_DIR = STORAGE_DIR / "uploads"
REPORT_DIR = STORAGE_DIR / "reports"
MAX_UPLOAD_BYTES = int(os.getenv("MAX_UPLOAD_BYTES", str(2 * 1024 * 1024 * 1024)))
MAX_ZIP_FILES = int(os.getenv("MAX_ZIP_FILES", "10000"))
MAX_ZIP_UNCOMPRESSED_BYTES = int(os.getenv("MAX_ZIP_UNCOMPRESSED_BYTES", str(4 * 1024 * 1024 * 1024)))
STORAGE_DIR.mkdir(parents=True, exist_ok=True)

def sanitize_filename(value: str) -> str:
    cleaned = "".join(c if c.isalnum() or c in "-_." else "_" for c in value)
    return cleaned[:180] or "upload"

def safe_extract_zip(archive_path: Path, destination: Path) -> None:
    destination = destination.resolve()
    total_size = 0
    with ZipFile(archive_path) as archive:
        members = archive.infolist()
        if len(members) > MAX_ZIP_FILES:
            raise HTTPException(status_code=413, detail=f"Archive trop volumineuse: {len(members)} fichiers")
        for member in members:
            total_size += max(member.file_size, 0)
            if total_size > MAX_ZIP_UNCOMPRESSED_BYTES:
                raise HTTPException(status_code=413, detail="Archive ZIP trop volumineuse apres extraction")
            target_path = (destination / member.filename).resolve()
            if not str(target_path).startswith(str(destination)):
                raise HTTPException(status_code=400, detail="Archive ZIP invalide: chemin dangereux detecte")
        archive.extractall(destination)


def get_logo_path() -> str | None:
    config_path = BASE_DIR / "logo_config.json"
    if config_path.exists():
        try:
            return json.loads(config_path.read_text(encoding="utf-8")).get("logo_path")
        except Exception:
            return None
    return None


def risk_badge(level: str | None) -> dict:
    value = (level or "").lower()
    if any(word in value for word in ["critical", "critique", "noir", "urgent"]):
        return {"label": "Critique", "emoji": "⚫", "class": "risk-critical"}
    if any(word in value for word in ["high", "haut", "rouge", "danger"]):
        return {"label": "Élevé", "emoji": "🔴", "class": "risk-high"}
    if any(word in value for word in ["warning", "warn", "suspect", "orange", "moyen"]):
        return {"label": "Surveillance", "emoji": "🟠", "class": "risk-warning"}
    if value:
        return {"label": level, "emoji": "🟢", "class": "risk-ok"}
    return {"label": "Non évalué", "emoji": "⚪", "class": "risk-none"}


def build_dashboard_context(request: Request, session: Session, user: User, q: str | None = None) -> dict:
    if q:
        query = f"%{q}%"
        clients = session.scalars(select(Client).where(Client.name.ilike(query)).order_by(Client.created_at.desc())).all()
        machines = session.scalars(select(Machine).where(
            (Machine.machine_name.ilike(query)) | (Machine.bios_serial.ilike(query)) |
            (Machine.manufacturer.ilike(query)) | (Machine.model.ilike(query))
        ).order_by(Machine.last_intervention.desc().nulls_last())).all()
        interventions = session.scalars(select(Intervention).where(
            (Intervention.title.ilike(query)) | (Intervention.machine_name.ilike(query)) |
            (Intervention.bios_serial.ilike(query)) | (Intervention.status.ilike(query))
        ).order_by(Intervention.created_at.desc())).all()
        parts = session.scalars(select(Part).where(
            (Part.brand.ilike(query)) | (Part.model.ilike(query)) |
            (Part.serial_number.ilike(query)) | (Part.part_type.ilike(query))
        ).order_by(Part.created_at.desc())).all()
        invoices = session.scalars(select(Invoice).where(Invoice.invoice_number.ilike(query)).order_by(Invoice.created_at.desc())).all()
        tickets = session.scalars(select(Ticket).where(
            (Ticket.title.ilike(query)) | (Ticket.description.ilike(query)) |
            (Ticket.priority.ilike(query)) | (Ticket.status.ilike(query))
        ).order_by(Ticket.created_at.desc())).all()
    else:
        clients = session.scalars(select(Client).order_by(Client.created_at.desc())).all()
        interventions = session.scalars(select(Intervention).order_by(Intervention.created_at.desc())).all()
        machines = session.scalars(select(Machine).order_by(Machine.last_intervention.desc().nulls_last())).all()
        parts = session.scalars(select(Part).order_by(Part.created_at.desc())).all()
        invoices = session.scalars(select(Invoice).order_by(Invoice.created_at.desc())).all()
        tickets = session.scalars(select(Ticket).order_by(Ticket.created_at.desc())).all()

    critical_words = ("critical", "critique", "rouge", "noir", "urgent", "danger", "high")
    warning_words = ("warning", "suspect", "orange", "moyen", "surveillance")
    disk_critical = [i for i in interventions if any(w in ((i.disk_risk or "") + " " + (i.data_loss_risk or "")).lower() for w in critical_words)]
    disk_warning = [i for i in interventions if any(w in ((i.disk_risk or "") + " " + (i.data_loss_risk or "")).lower() for w in warning_words)]
    open_tickets = [t for t in tickets if (t.status or "").lower() in {"open", "in_progress", "nouveau", "ouvert"}]
    now = datetime.utcnow()
    month_invoices = [i for i in invoices if i.created_at.year == now.year and i.created_at.month == now.month and (i.status or "").lower() != "cancelled"]
    monthly_revenue = sum(float(i.total or 0) for i in month_invoices)

    alerts = []
    for item in disk_critical[:8]:
        alerts.append({"level": "critical", "title": item.title, "message": f"Risque disque/données: {item.disk_risk or item.data_loss_risk}", "url": item.report_path})
    for item in disk_warning[:8]:
        alerts.append({"level": "warning", "title": item.title, "message": f"À surveiller: {item.disk_risk or item.data_loss_risk}", "url": item.report_path})
    for ticket in open_tickets[:6]:
        alerts.append({"level": "ticket", "title": ticket.title, "message": f"Ticket {ticket.priority} · {ticket.status}", "url": "/tickets"})

    stats = {
        "clients": len(clients),
        "machines": len(machines),
        "interventions": len(interventions),
        "disk_critical": len(disk_critical),
        "disk_warning": len(disk_warning),
        "tickets_open": len(open_tickets),
        "monthly_revenue": monthly_revenue,
        "parts_stock": sum(max(p.quantity or 0, 0) for p in parts),
    }

    return {
        "request": request,
        "clients": clients,
        "interventions": interventions,
        "machines": machines,
        "parts": parts,
        "invoices": invoices,
        "tickets": tickets,
        "user": user,
        "logo_path": get_logo_path(),
        "stats": stats,
        "alerts": alerts[:12],
        "recent_interventions": interventions[:10],
        "recent_tickets": tickets[:8],
        "risk_machines": [m for m in machines if any(i.disk_risk and str(i.disk_risk).lower() not in {"healthy", "ok", "faible"} for i in m.interventions)][:10],
        "atelier_statuses": ["nouvelle", "en_attente", "en_cours", "termine", "livre", "facture"],
        "risk_badge": risk_badge,
        "search_query": q or "",
    }



def intervention_url(intervention: Intervention) -> str:
    if intervention.report_path:
        return intervention.report_path
    return f"/intervention/{intervention.id}/label"

def invoice_html(invoice: Invoice) -> str:
    client = invoice.client
    intervention = invoice.intervention
    created = invoice.created_at.strftime("%d/%m/%Y")
    due = invoice.due_date.strftime("%d/%m/%Y") if invoice.due_date else ""
    return f"""<!doctype html>
<html lang="fr"><head><meta charset="utf-8"><title>Facture {invoice.invoice_number}</title>
<style>
body{{font-family:Segoe UI,Arial,sans-serif;background:#f5f7fb;color:#172033;margin:40px}}
.page{{max-width:900px;margin:auto;background:white;border-radius:18px;padding:36px;box-shadow:0 20px 50px #0001}}
h1{{color:#0f766e}} table{{width:100%;border-collapse:collapse;margin-top:24px}} th,td{{border-bottom:1px solid #e5e7eb;padding:10px;text-align:left}}
.total{{font-size:28px;font-weight:800;color:#0f766e}} @media print{{body{{background:white}}.page{{box-shadow:none}}}}
</style></head><body><main class="page">
<h1>Facture {invoice.invoice_number}</h1>
<p><strong>Client :</strong> {(client.name if client else "Client")}</p>
<p><strong>Date :</strong> {created} &nbsp; <strong>Échéance :</strong> {due}</p>
<table><tr><th>Désignation</th><th>Montant HT</th><th>TVA</th><th>Total</th></tr>
<tr><td>{(intervention.title if intervention else "Intervention Restor-PC RescueGrid")}</td><td>{invoice.amount:.2f} €</td><td>{invoice.tax:.2f} €</td><td>{invoice.total:.2f} €</td></tr></table>
<p class="total">Total à payer : {invoice.total:.2f} €</p>
<p>Statut : {invoice.status}</p>
<p style="color:#667085;margin-top:40px">Document généré par Restor-PC RescueGrid.</p>
</main></body></html>"""

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


app = FastAPI(title="Restor-PC RescueGrid")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


@app.on_event("startup")
def on_startup() -> None:
    STORAGE_DIR.mkdir(exist_ok=True)
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    init_db()
    with SessionLocal() as session:
        from .auth import create_default_admin
        create_default_admin(session)


@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})


@app.post("/login")
def login(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    session: Session = Depends(get_session),
):
    from .auth import authenticate_user, create_access_token
    user = authenticate_user(username, password, session)
    if not user:
        return templates.TemplateResponse("login.html", {"request": request, "error": "Identifiants invalides"})
    token = create_access_token({"sub": user.username})
    response = RedirectResponse("/", status_code=303)
    response.set_cookie("access_token", token, httponly=True, max_age=480*60)
    user.last_login = datetime.utcnow()
    session.commit()
    return response


@app.get("/logout")
def logout():
    response = RedirectResponse("/login", status_code=303)
    response.delete_cookie("access_token")
    return response


@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request, session: Session = Depends(get_session)):
    from .auth import get_current_user
    user = get_current_user(request, session)
    if not user:
        return RedirectResponse("/login", status_code=303)
    return templates.TemplateResponse("dashboard.html", build_dashboard_context(request, session, user))


@app.get("/search")
def search(request: Request, q: str = "", session: Session = Depends(get_session)):
    from .auth import get_current_user
    user = get_current_user(request, session)
    if not user:
        return RedirectResponse("/login", status_code=303)
    return templates.TemplateResponse("dashboard.html", build_dashboard_context(request, session, user, q=q.strip()))


@app.get("/client/{client_id}", response_class=HTMLResponse)
def client_detail(client_id: int, request: Request, session: Session = Depends(get_session)):
    from .auth import get_current_user, require_auth
    user = get_current_user(request, session)
    if not user:
        return RedirectResponse("/login", status_code=303)
    client = session.scalars(select(Client).where(Client.id == client_id)).first()
    if not client:
        raise HTTPException(status_code=404, detail="Client introuvable")
    interventions = session.scalars(
        select(Intervention).where(Intervention.client_id == client_id).order_by(Intervention.created_at.desc())
    ).all()
    return templates.TemplateResponse(
        "client_detail.html",
        {"request": request, "client": client, "interventions": interventions, "user": user},
    )


@app.get("/machine/{machine_id}", response_class=HTMLResponse)
def machine_detail(machine_id: int, request: Request, session: Session = Depends(get_session)):
    from .auth import get_current_user
    user = get_current_user(request, session)
    if not user:
        return RedirectResponse("/login", status_code=303)
    machine = session.scalars(select(Machine).where(Machine.id == machine_id)).first()
    if not machine:
        raise HTTPException(status_code=404, detail="Machine introuvable")
    interventions = session.scalars(
        select(Intervention).where(Intervention.machine_id == machine_id).order_by(Intervention.created_at.desc())
    ).all()
    return templates.TemplateResponse(
        "machine_detail.html",
        {"request": request, "machine": machine, "interventions": interventions, "user": user},
    )


@app.post("/clients")
def create_client(
    request: Request,
    name: str = Form(...),
    email: str = Form(""),
    phone: str = Form(""),
    session: Session = Depends(get_session),
):
    from .auth import get_user_or_redirect
    user, redirect = get_user_or_redirect(request, session)
    if redirect:
        return redirect
    client = Client(name=name.strip(), email=email or None, phone=phone or None)
    session.add(client)
    session.commit()
    return RedirectResponse("/", status_code=303)


@app.post("/machines")
def create_machine(
    request: Request,
    bios_serial: str = Form(""),
    machine_name: str = Form(""),
    manufacturer: str = Form(""),
    model: str = Form(""),
    session: Session = Depends(get_session),
):
    from .auth import get_user_or_redirect
    user, redirect = get_user_or_redirect(request, session)
    if redirect:
        return redirect
    machine = Machine(
        bios_serial=bios_serial or None,
        machine_name=machine_name or None,
        manufacturer=manufacturer or None,
        model=model or None,
    )
    session.add(machine)
    session.commit()
    return RedirectResponse("/", status_code=303)


@app.post("/interventions")
def create_intervention(
    request: Request,
    title: str = Form(...),
    client_id: int = Form(...),
    machine_id: int = Form(0),
    machine_name: str = Form(""),
    status: str = Form("nouvelle"),
    session: Session = Depends(get_session),
):
    from .auth import get_user_or_redirect
    user, redirect = get_user_or_redirect(request, session)
    if redirect:
        return redirect
    intervention = Intervention(
        client_id=client_id,
        machine_id=machine_id if machine_id > 0 else None,
        title=title.strip(),
        machine_name=machine_name or None,
        status=status,
    )
    session.add(intervention)
    session.commit()
    return RedirectResponse("/", status_code=303)


@app.post("/upload")
async def upload_intervention(
    request: Request,
    client_name: str = Form(...),
    file: UploadFile = File(...),
    upload_key: str = Form(""),
    session: Session = Depends(get_session),
):
    from .auth import verify_upload_access
    if not verify_upload_access(request, session, upload_key or None):
        raise HTTPException(status_code=401, detail="Authentification requise pour l'import ZIP")
    if not file.filename or not file.filename.lower().endswith(".zip"):
        raise HTTPException(status_code=400, detail="Archive ZIP requise")

    safe_name = sanitize_filename(client_name)
    safe_file = sanitize_filename(Path(file.filename).name)
    archive_path = UPLOAD_DIR / f"{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}_{safe_name}_{safe_file}"

    written = 0
    with archive_path.open("wb") as buffer:
        while True:
            chunk = await file.read(1024 * 1024)
            if not chunk:
                break
            written += len(chunk)
            if written > MAX_UPLOAD_BYTES:
                archive_path.unlink(missing_ok=True)
                raise HTTPException(status_code=413, detail="Archive trop volumineuse")
            buffer.write(chunk)

    extracted_dir = REPORT_DIR / archive_path.stem
    extracted_dir.mkdir(parents=True, exist_ok=True)
    safe_extract_zip(archive_path, extracted_dir)

    inventory_path = extracted_dir / "inventory.json"
    report_path = extracted_dir / "rapport.html"
    inventory = {}
    if inventory_path.exists():
        try:
            inventory = json.loads(inventory_path.read_text(encoding="utf-8-sig"))
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            raise HTTPException(status_code=422, detail=f"inventory.json invalide: {e}")

    # Client
    client = session.scalars(select(Client).where(Client.name == client_name)).first()
    if client is None:
        client = Client(name=client_name)
        session.add(client)
        session.commit()
        session.refresh(client)

    # Machine / Historique
    bios = inventory.get("bios") or {}
    bios_serial = bios.get("SerialNumber")
    machine_name = inventory.get("machine", {}).get("CsName")
    machine_id = None

    if bios_serial:
        machine = session.scalars(select(Machine).where(Machine.bios_serial == bios_serial)).first()
        if machine is None:
            machine = Machine(
                bios_serial=bios_serial,
                machine_name=machine_name,
                manufacturer=bios.get("Manufacturer"),
                model=inventory.get("machine", {}).get("CsModel"),
            )
            session.add(machine)
            session.commit()
            session.refresh(machine)
        machine.last_intervention = datetime.utcnow()
        machine.machine_name = machine_name
        session.commit()
        machine_id = machine.id

    # Intervention
    machine = inventory.get("machine") or {}
    health = inventory.get("health") or {}
    disk_risk = inventory.get("disk_risk") or {}
    offline_windows = inventory.get("offline_windows") or {}
    intervention = Intervention(
        client_id=client.id,
        machine_id=machine_id,
        title=archive_path.stem,
        machine_name=machine.get("CsName") or None,
        bios_serial=bios_serial,
        health_score=health.get("global_score"),
        data_loss_risk=health.get("data_loss_risk"),
        disk_risk=disk_risk.get("level") if isinstance(disk_risk, dict) else None,
        offline_windows="oui" if isinstance(offline_windows, dict) and offline_windows.get("enabled") else "non",
        status="rapport importe",
        archive_path=str(archive_path.relative_to(STORAGE_DIR)),
        report_path=str(report_path.relative_to(STORAGE_DIR)) if report_path.exists() else None,
    )
    session.add(intervention)
    session.commit()
    return RedirectResponse("/", status_code=303)


@app.post("/delete/client/{client_id}")
def delete_client(client_id: int, request: Request, session: Session = Depends(get_session)):
    from .auth import get_admin_or_redirect
    user, redirect = get_admin_or_redirect(request, session)
    if redirect:
        return redirect
    client = session.scalars(select(Client).where(Client.id == client_id)).first()
    if client:
        session.delete(client)
        session.commit()
    return RedirectResponse("/", status_code=303)


@app.post("/delete/intervention/{intervention_id}")
def delete_intervention(intervention_id: int, request: Request, session: Session = Depends(get_session)):
    from .auth import get_admin_or_redirect
    user, redirect = get_admin_or_redirect(request, session)
    if redirect:
        return redirect
    intervention = session.scalars(select(Intervention).where(Intervention.id == intervention_id)).first()
    if intervention:
        session.delete(intervention)
        session.commit()
    return RedirectResponse("/", status_code=303)


@app.get("/parts", response_class=HTMLResponse)
def parts_list(request: Request, session: Session = Depends(get_session)):
    from .auth import get_current_user
    user = get_current_user(request, session)
    if not user:
        return RedirectResponse("/login", status_code=303)
    parts = session.scalars(select(Part).order_by(Part.created_at.desc())).all()
    return templates.TemplateResponse("parts.html", {"request": request, "parts": parts, "user": user})


@app.post("/parts")
def create_part(
    request: Request,
    part_type: str = Form(...),
    brand: str = Form(""),
    model: str = Form(""),
    serial_number: str = Form(""),
    capacity_gb: int = Form(0),
    quantity: int = Form(1),
    notes: str = Form(""),
    session: Session = Depends(get_session),
):
    from .auth import get_user_or_redirect
    user, redirect = get_user_or_redirect(request, session)
    if redirect:
        return redirect
    part = Part(
        part_type=part_type,
        brand=brand or None,
        model=model or None,
        serial_number=serial_number or None,
        capacity_gb=capacity_gb if capacity_gb > 0 else None,
        quantity=quantity,
        notes=notes or None,
    )
    session.add(part)
    session.commit()
    return RedirectResponse("/parts", status_code=303)


@app.post("/delete/part/{part_id}")
def delete_part(part_id: int, request: Request, session: Session = Depends(get_session)):
    from .auth import get_admin_or_redirect
    user, redirect = get_admin_or_redirect(request, session)
    if redirect:
        return redirect
    part = session.scalars(select(Part).where(Part.id == part_id)).first()
    if part:
        session.delete(part)
        session.commit()
    return RedirectResponse("/parts", status_code=303)


@app.post("/upload-logo")
async def upload_logo(request: Request, file: UploadFile = File(...), session: Session = Depends(get_session)):
    from .auth import get_current_user
    user = get_current_user(request, session)
    if not user:
        raise HTTPException(status_code=401, detail="Non autorise")
    
    if not file.content_type or not file.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="Fichier image requis")
    
    logo_dir = STORAGE_DIR / "logos"
    logo_dir.mkdir(exist_ok=True)
    logo_path = logo_dir / "logo.png"
    
    with logo_path.open("wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
    
    # Mettre à jour le chemin dans la session (ou base de données)
    # Pour simplifier, on utilise un fichier de config
    config_path = BASE_DIR / "logo_config.json"
    config_path.write_text(json.dumps({"logo_path": "logos/logo.png"}), encoding="utf-8")
    
    return RedirectResponse("/", status_code=303)


@app.get("/logo-config")
def get_logo_config():
    config_path = BASE_DIR / "logo_config.json"
    if config_path.exists():
        config = json.loads(config_path.read_text(encoding="utf-8"))
        return {"logo_path": config.get("logo_path")}
    return {"logo_path": None}


# ===== FACTURATION v5.0 =====
@app.get("/invoices", response_class=HTMLResponse)
def invoices_list(request: Request, session: Session = Depends(get_session)):
    from .auth import get_current_user
    user = get_current_user(request, session)
    if not user:
        return RedirectResponse("/login", status_code=303)
    invoices = session.scalars(select(Invoice).order_by(Invoice.created_at.desc())).all()
    return templates.TemplateResponse("invoices.html", {"request": request, "invoices": invoices, "user": user})


@app.post("/invoices")
def create_invoice(
    request: Request,
    intervention_id: int = Form(...),
    amount: float = Form(...),
    tax: float = Form(0.0),
    status: str = Form("draft"),
    due_date: str = Form(""),
    notes: str = Form(""),
    session: Session = Depends(get_session),
):
    from .auth import get_user_or_redirect
    user, redirect = get_user_or_redirect(request, session)
    if redirect:
        return redirect
    intervention = session.scalars(select(Intervention).where(Intervention.id == intervention_id)).first()
    if not intervention:
        raise HTTPException(status_code=404, detail="Intervention introuvable")
    
    total = amount + tax
    invoice_number = f"INV-{datetime.utcnow().strftime('%Y%m%d')}-{intervention_id:04d}"
    
    invoice = Invoice(
        intervention_id=intervention_id,
        client_id=intervention.client_id,
        invoice_number=invoice_number,
        amount=amount,
        tax=tax,
        total=total,
        status=status,
        due_date=datetime.strptime(due_date, "%Y-%m-%d") if due_date else None,
        notes=notes or None,
    )
    session.add(invoice)
    session.commit()
    return RedirectResponse("/invoices", status_code=303)


@app.post("/delete/invoice/{invoice_id}")
def delete_invoice(invoice_id: int, request: Request, session: Session = Depends(get_session)):
    from .auth import get_admin_or_redirect
    user, redirect = get_admin_or_redirect(request, session)
    if redirect:
        return redirect
    invoice = session.scalars(select(Invoice).where(Invoice.id == invoice_id)).first()
    if invoice:
        session.delete(invoice)
        session.commit()
    return RedirectResponse("/invoices", status_code=303)


# ===== TICKETS v5.0 =====
@app.get("/tickets", response_class=HTMLResponse)
def tickets_list(request: Request, session: Session = Depends(get_session)):
    from .auth import get_current_user
    user = get_current_user(request, session)
    if not user:
        return RedirectResponse("/login", status_code=303)
    tickets = session.scalars(select(Ticket).order_by(Ticket.created_at.desc())).all()
    return templates.TemplateResponse("tickets.html", {"request": request, "tickets": tickets, "user": user})


@app.post("/tickets")
def create_ticket(
    request: Request,
    intervention_id: int = Form(...),
    title: str = Form(...),
    description: str = Form(""),
    priority: str = Form("medium"),
    status: str = Form("open"),
    session: Session = Depends(get_session),
):
    from .auth import get_user_or_redirect
    user, redirect = get_user_or_redirect(request, session)
    if redirect:
        return redirect
    intervention = session.scalars(select(Intervention).where(Intervention.id == intervention_id)).first()
    if not intervention:
        raise HTTPException(status_code=404, detail="Intervention introuvable")
    
    ticket = Ticket(
        intervention_id=intervention_id,
        client_id=intervention.client_id,
        title=title,
        description=description or None,
        priority=priority,
        status=status,
    )
    session.add(ticket)
    session.commit()
    return RedirectResponse("/tickets", status_code=303)


@app.post("/delete/ticket/{ticket_id}")
def delete_ticket(ticket_id: int, request: Request, session: Session = Depends(get_session)):
    from .auth import get_admin_or_redirect
    user, redirect = get_admin_or_redirect(request, session)
    if redirect:
        return redirect
    ticket = session.scalars(select(Ticket).where(Ticket.id == ticket_id)).first()
    if ticket:
        session.delete(ticket)
        session.commit()
    return RedirectResponse("/tickets", status_code=303)


@app.get("/export/interventions.xlsx")
def export_interventions_excel(request: Request, session: Session = Depends(get_session)):
    from .auth import get_user_or_redirect
    user, redirect = get_user_or_redirect(request, session)
    if redirect:
        return redirect
    interventions = session.scalars(select(Intervention).order_by(Intervention.created_at.desc())).all()
    
    wb = Workbook()
    ws = wb.active
    ws.title = "Interventions"
    ws.append(["ID", "Date", "Client", "Machine", "Titre", "Score", "Risque disque", "Offline", "Risque donnees", "Statut"])
    for item in interventions:
        ws.append([
            item.id,
            item.created_at.strftime("%Y-%m-%d %H:%M"),
            item.client.name if item.client else "",
            item.machine_name or "",
            item.title,
            item.health_score or "",
            item.disk_risk or "",
            item.offline_windows or "",
            item.data_loss_risk or "",
            item.status,
        ])
    
    from io import BytesIO
    stream = BytesIO()
    wb.save(stream)
    stream.seek(0)
    return StreamingResponse(
        stream,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=interventions.xlsx"},
    )



@app.get("/api/stats")
def api_stats(request: Request, session: Session = Depends(get_session)):
    from .auth import get_current_user
    user = get_current_user(request, session)
    if not user:
        raise HTTPException(status_code=401, detail="Non autorise")
    context = build_dashboard_context(request, session, user)
    return {"stats": context["stats"], "alerts": context["alerts"]}


@app.get("/tools", response_class=HTMLResponse)
def tools_page(request: Request, session: Session = Depends(get_session)):
    from .auth import get_current_user
    user = get_current_user(request, session)
    if not user:
        return RedirectResponse("/login", status_code=303)
    return templates.TemplateResponse(
        "tools.html",
        {"request": request, "user": user, "logo_path": get_logo_path()},
    )




@app.post("/intervention/{intervention_id}/status")
def update_intervention_status(
    intervention_id: int,
    request: Request,
    status: str = Form(...),
    session: Session = Depends(get_session),
):
    from .auth import get_user_or_redirect
    user, redirect = get_user_or_redirect(request, session)
    if redirect:
        return redirect
    intervention = session.scalars(select(Intervention).where(Intervention.id == intervention_id)).first()
    if not intervention:
        raise HTTPException(status_code=404, detail="Intervention introuvable")
    allowed = {"nouvelle", "en_attente", "en_cours", "termine", "livre", "facture"}
    intervention.status = status if status in allowed else "nouvelle"
    session.commit()
    return RedirectResponse("/", status_code=303)


@app.get("/intervention/{intervention_id}/label", response_class=HTMLResponse)
def intervention_label(intervention_id: int, request: Request, session: Session = Depends(get_session)):
    from .auth import get_current_user
    user = get_current_user(request, session)
    if not user:
        return RedirectResponse("/login", status_code=303)
    intervention = session.scalars(select(Intervention).where(Intervention.id == intervention_id)).first()
    if not intervention:
        raise HTTPException(status_code=404, detail="Intervention introuvable")
    client = intervention.client
    machine = intervention.machine
    html = f"""<!doctype html><html lang="fr"><head><meta charset="utf-8"><title>Étiquette intervention</title>
<style>
body{{font-family:Segoe UI,Arial,sans-serif;background:white;margin:20px}}
.label{{width:95mm;border:2px solid #111827;border-radius:8px;padding:12px}}
h1{{font-size:18px;margin:0 0 8px;color:#0f766e}} .id{{font-size:22px;font-weight:800}} p{{margin:4px 0}}
.qr{{width:90px;height:90px;border:1px dashed #94a3b8;display:flex;align-items:center;justify-content:center;font-size:11px;color:#64748b}}
@media print{{button{{display:none}} body{{margin:0}}}}
</style></head><body><button onclick="print()">Imprimer</button><div class="label">
<h1>Restor-PC RescueGrid</h1><div class="id">INT-{intervention.id:06d}</div>
<p><strong>Client :</strong> {(client.name if client else "")}</p>
<p><strong>Machine :</strong> {intervention.machine_name or (machine.machine_name if machine else "")}</p>
<p><strong>BIOS :</strong> {intervention.bios_serial or ""}</p>
<p><strong>Statut :</strong> {intervention.status}</p>
<p><strong>Date :</strong> {intervention.created_at.strftime("%d/%m/%Y %H:%M")}</p>
<div class="qr">QR / INT-{intervention.id:06d}</div>
</div></body></html>"""
    return HTMLResponse(html)


@app.get("/invoice/{invoice_id}/pdf", response_class=HTMLResponse)
def invoice_pdf(invoice_id: int, request: Request, session: Session = Depends(get_session)):
    from .auth import get_current_user
    user = get_current_user(request, session)
    if not user:
        return RedirectResponse("/login", status_code=303)
    invoice = session.scalars(select(Invoice).where(Invoice.id == invoice_id)).first()
    if not invoice:
        raise HTTPException(status_code=404, detail="Facture introuvable")
    return HTMLResponse(invoice_html(invoice))


@app.get("/backup/database")
def backup_database(request: Request):
    from .auth import get_current_user
    with SessionLocal() as session:
        user = get_current_user(request, session)
        if not user:
            raise HTTPException(status_code=401, detail="Non autorise")
    db_path = BASE_DIR / "rescuegrid.db"
    if not db_path.exists():
        db_path = BASE_DIR / "app.db"
    if not db_path.exists():
        raise HTTPException(status_code=404, detail="Base SQLite introuvable")
    def iterfile():
        with open(db_path, "rb") as f:
            yield from f
    return StreamingResponse(iterfile(), media_type="application/octet-stream", headers={"Content-Disposition": "attachment; filename=rescuegrid_backup.db"})


@app.get("/health")
def healthcheck():
    return {"status": "ok"}


@app.get("/storage/{file_path:path}")
def serve_storage_file(file_path: str, request: Request, session: Session = Depends(get_session)):
    from .auth import get_user_or_redirect
    user, redirect = get_user_or_redirect(request, session)
    if redirect:
        return redirect
    target = resolve_storage_path(file_path)
    if not target.is_file():
        raise HTTPException(status_code=404, detail="Fichier introuvable")
    return FileResponse(target)


@app.get("/intervention/{intervention_id}/download/zip")
def download_intervention_zip(intervention_id: int, request: Request, session: Session = Depends(get_session)):
    from .auth import get_user_or_redirect
    user, redirect = get_user_or_redirect(request, session)
    if redirect:
        return redirect
    intervention = session.scalars(select(Intervention).where(Intervention.id == intervention_id)).first()
    if not intervention or not intervention.archive_path:
        raise HTTPException(status_code=404, detail="Archive ZIP introuvable")
    target = resolve_storage_path(intervention.archive_path)
    if not target.is_file():
        raise HTTPException(status_code=404, detail="Archive ZIP introuvable")
    return FileResponse(target, filename=target.name, media_type="application/zip")


@app.get("/intervention/{intervention_id}/download/report")
def download_intervention_report(intervention_id: int, request: Request, session: Session = Depends(get_session)):
    from .auth import get_user_or_redirect
    user, redirect = get_user_or_redirect(request, session)
    if redirect:
        return redirect
    intervention = session.scalars(select(Intervention).where(Intervention.id == intervention_id)).first()
    if not intervention or not intervention.report_path:
        raise HTTPException(status_code=404, detail="Rapport introuvable")
    target = resolve_storage_path(intervention.report_path)
    if not target.is_file():
        raise HTTPException(status_code=404, detail="Rapport introuvable")
    return FileResponse(target, filename=target.name, media_type="text/html")


@app.get("/intervention/{intervention_id}/download/manifest")
def download_intervention_manifest(intervention_id: int, request: Request, session: Session = Depends(get_session)):
    from .auth import get_user_or_redirect
    user, redirect = get_user_or_redirect(request, session)
    if redirect:
        return redirect
    intervention = session.scalars(select(Intervention).where(Intervention.id == intervention_id)).first()
    if not intervention:
        raise HTTPException(status_code=404, detail="Intervention introuvable")
    folder = intervention_dir(intervention)
    if not folder:
        raise HTTPException(status_code=404, detail="Dossier intervention introuvable")
    target = (folder / "evidence_manifest.json").resolve()
    if not str(target).startswith(str(STORAGE_DIR.resolve())) or not target.is_file():
        raise HTTPException(status_code=404, detail="Manifeste introuvable")
    return FileResponse(target, filename="evidence_manifest.json", media_type="application/json")
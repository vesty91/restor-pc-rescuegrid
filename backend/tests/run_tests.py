"""Tests d'intÃ©gration Restor-PC RescueGrid â€” exÃ©cution autonome."""
from __future__ import annotations

import io
import json
import os
import re
import sys
import tempfile
import time
import zipfile
from pathlib import Path

import pyotp

# Backend root on path
BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))
os.chdir(BACKEND_DIR)

# Base de test isolÃ©e
TEST_DB = BACKEND_DIR / "test_rescuegrid.db"
if TEST_DB.exists():
    TEST_DB.unlink()

os.environ["DATABASE_URL"] = f"sqlite:///{TEST_DB.as_posix()}"
os.environ["SECRET_KEY"] = "test-secret-key"
os.environ["ADMIN_PASSWORD"] = "testadmin2026"
os.environ.pop("UPLOAD_API_KEY", None)

from fastapi import HTTPException
from fastapi.testclient import TestClient  # noqa: E402

from app.database import SessionLocal, init_db  # noqa: E402
from app.auth import create_default_admin  # noqa: E402
from app.main import app, safe_extract_zip, sanitize_filename  # noqa: E402

init_db()
with SessionLocal() as _session:
    create_default_admin(_session)

def record(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, ok, detail))
    status = "PASS" if ok else "FAIL"
    print(f"[{status}] {name}" + (f" â€” {detail}" if detail else ""))


def form(data: dict | None = None, *, c: TestClient | None = None) -> dict:
    """Ajoute le jeton CSRF (cookie double-submit) aux donnÃ©es de formulaire."""
    c = c or client
    payload = dict(data or {})
    token = c.cookies.get("csrf_token")
    if not token:
        c.get("/health")
        token = c.cookies.get("csrf_token")
    if token:
        payload["csrf_token"] = token
    return payload


def make_client() -> TestClient:
    """TestClient qui injecte automatiquement le jeton CSRF sur les POST formulaire."""
    c = TestClient(app)
    real_post = c.post

    def post(url, data=None, json=None, **kwargs):
        # Exemptés CSRF : uniquement /upload (agent) et webhooks Stripe — pas /upload-logo.
        path = str(url).split("?", 1)[0]
        if json is None and path != "/upload" and not path.startswith("/stripe/"):
            token_data = form(dict(data or {}) if isinstance(data, dict) or data is None else {}, c=c)
            token = token_data.get("csrf_token", "")
            headers = dict(kwargs.pop("headers", None) or {})
            if token:
                headers["X-CSRF-Token"] = token
            kwargs["headers"] = headers
            if kwargs.get("files") is not None:
                data = token_data
            elif data is None or isinstance(data, dict):
                data = token_data
        return real_post(url, data=data, json=json, **kwargs)

    c.post = post  # type: ignore[method-assign]
    return c


results: list[tuple[str, bool, str]] = []
ADMIN_TOTP_SECRET: str | None = None
client = make_client()


def _extract_totp_secret(html: str) -> str | None:
    match = re.search(r'<div class="secret">([A-Z0-9]+)</div>', html)
    return match.group(1) if match else None


def login() -> None:
    """Connexion admin de bout en bout, y compris le premier enrÃ´lement 2FA
    obligatoire (voir main.py POST /login, /2fa/setup) â€” l'admin de test crÃ©Ã©
    par create_default_admin() n'a jamais encore de 2FA active."""
    global ADMIN_TOTP_SECRET
    r = client.post("/login", data=form({"username": "admin", "password": "testadmin2026"}), follow_redirects=False)
    if r.status_code == 303 and r.headers.get("location") == "/2fa/setup":
        setup_page = client.get("/2fa/setup")
        secret = _extract_totp_secret(setup_page.text)
        ADMIN_TOTP_SECRET = secret
        code = pyotp.TOTP(secret).now() if secret else ""
        r2 = client.post("/2fa/setup", data=form({"code": code}), follow_redirects=False)
        record("2FA enrÃ´lement admin", r2.status_code == 200 and "codes de secours" in r2.text.lower(), f"status={r2.status_code}")
        r3 = client.post("/2fa/setup/continue", data=form({}), follow_redirects=False)
        record("login admin (aprÃ¨s 2FA)", r3.status_code == 303 and "access_token" in r3.cookies, f"status={r3.status_code}")
    else:
        record("login admin", r.status_code == 303 and "access_token" in r.cookies, f"status={r.status_code}")


def test_health() -> None:
    r = client.get("/health")
    record("GET /health", r.status_code == 200 and r.json().get("status") == "ok", str(r.json()))


def test_login_page() -> None:
    r = client.get("/login")
    record("GET /login", r.status_code == 200 and "Restor-PC" in r.text, f"status={r.status_code}")


def test_dashboard_requires_auth() -> None:
    c = make_client()
    r = c.get("/", follow_redirects=False)
    record("GET / sans auth -> redirect login", r.status_code == 303 and r.headers.get("location") == "/login")


def test_create_client_requires_auth() -> None:
    c = make_client()
    r = c.post("/clients", data={"name": "Hacker"}, follow_redirects=False)
    record("POST /clients sans auth -> redirect", r.status_code == 303 and r.headers.get("location") == "/login")


def test_authenticated_dashboard() -> None:
    r = client.get("/")
    record("GET / dashboard authentifiÃ©", r.status_code == 200 and "Restor-PC RescueGrid" in r.text)


def test_create_client_authenticated() -> None:
    r = client.post("/clients", data={"name": "Client Test", "email": "test@example.com", "phone": "0600000000"}, follow_redirects=False)
    record("POST /clients authentifiÃ©", r.status_code == 303)


def test_search() -> None:
    r = client.get("/search?q=Client+Test")
    record("GET /search", r.status_code == 200 and "Client Test" in r.text)


def test_storage_requires_auth() -> None:
    c = make_client()
    r = c.get("/storage/reports/fake.html", follow_redirects=False)
    record("GET /storage sans auth -> redirect", r.status_code == 303)


def test_export_requires_auth() -> None:
    c = make_client()
    r = c.get("/export/interventions.xlsx", follow_redirects=False)
    record("GET /export sans auth -> redirect", r.status_code == 303)


def test_export_authenticated() -> None:
    r = client.get("/export/interventions.xlsx")
    record(
        "GET /export authentifiÃ©",
        r.status_code == 200 and "spreadsheetml" in r.headers.get("content-type", ""),
        r.headers.get("content-type", ""),
    )


def test_api_stats() -> None:
    r = client.get("/api/stats")
    record("GET /api/stats", r.status_code == 200 and "stats" in r.json(), str(r.json().get("stats", {})))


def test_sanitize_filename() -> None:
    record("sanitize_filename", sanitize_filename("../../etc/passwd") == ".._.._etc_passwd")


def test_safe_extract_zip_zipslip() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        dest = Path(tmp)
        zip_path = dest / "evil.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("../../escape.txt", "bad")
        try:
            safe_extract_zip(zip_path, dest / "out")
            record("safe_extract_zip anti-ZipSlip", False, "devrait lever une exception")
        except HTTPException as exc:
            record("safe_extract_zip anti-ZipSlip", exc.status_code == 400, f"status={exc.status_code}")


def make_sample_zip() -> io.BytesIO:
    buf = io.BytesIO()
    inventory = {
        "machine": {"CsName": "PC-TEST", "CsModel": "TestModel"},
        "bios": {"SerialNumber": "BIOS-TEST-123", "Manufacturer": "TestCorp"},
        "health": {"global_score": 97, "data_loss_risk": "Faible"},
        "disk_risk": {"level": "healthy"},
        "offline_windows": {"enabled": False},
    }
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("inventory.json", json.dumps(inventory, ensure_ascii=False))
        zf.writestr("rapport.html", "<html><body><h1>Rapport test</h1></body></html>")
        zf.writestr("evidence_manifest.json", json.dumps({"files": []}))
    buf.seek(0)
    return buf


def test_upload_zip_authenticated() -> None:
    buf = make_sample_zip()
    r = client.post(
        "/upload",
        data={"client_name": "Client ZIP Test"},
        files={"file": ("intervention_test.zip", buf, "application/zip")},
        follow_redirects=False,
    )
    record("POST /upload ZIP authentifiÃ©", r.status_code == 303, f"status={r.status_code}")


def test_upload_metadata_from_inventory() -> None:
    """/upload doit lire inventory.json (schÃ©ma rÃ©el produit par l'agent, voir
    make_sample_zip) et pas un manifest.json inexistant â€” bug corrigÃ© en v12.3
    qui laissait bios_serial/health_score toujours vides et cassait la
    dÃ©duplication des machines entre postes techniciens (mode multi-poste)."""
    from app.database import SessionLocal
    from app.models import Intervention
    from sqlalchemy import select

    with SessionLocal() as session:
        intervention = session.scalars(
            select(Intervention).where(Intervention.title.contains("PC-TEST"))
        ).first()
    if not intervention:
        record("MÃ©tadonnÃ©es upload (bios_serial/health_score)", False, "intervention introuvable")
        return
    ok = (
        intervention.bios_serial == "BIOS-TEST-123"
        and intervention.health_score == 97
        and intervention.disk_risk == "healthy"
        and intervention.data_loss_risk == "Faible"
    )
    record(
        "MÃ©tadonnÃ©es upload (bios_serial/health_score depuis inventory.json)",
        ok,
        f"bios={intervention.bios_serial} score={intervention.health_score} disk_risk={intervention.disk_risk}",
    )


def test_upload_creates_client_fiche() -> None:
    """POST /upload avec email/tel/adresse doit crÃ©er ou complÃ©ter la fiche Client."""
    from app.database import SessionLocal
    from app.models import Client
    from sqlalchemy import func, select

    buf = make_sample_zip()
    r = client.post(
        "/upload",
        data={
            "client_name": "Client Fiche USB",
            "client_email": "fiche.usb@example.com",
            "client_phone": "0601020304",
            "client_address": "12 rue Test 75000 Paris",
            "client_contact": "Jean Dupont",
            "send_report_email": "false",
        },
        files={"file": ("intervention_fiche.zip", buf, "application/zip")},
        follow_redirects=False,
    )
    if r.status_code != 303:
        record("POST /upload fiche client", False, f"status={r.status_code}")
        return

    with SessionLocal() as session:
        c = session.scalars(
            select(Client).where(func.lower(Client.name) == "client fiche usb")
        ).first()
    ok = (
        c is not None
        and c.email == "fiche.usb@example.com"
        and c.phone == "0601020304"
        and c.address == "12 rue Test 75000 Paris"
        and c.contact_name == "Jean Dupont"
    )
    record(
        "POST /upload crÃ©e/complÃ¨te fiche Client",
        ok,
        f"email={getattr(c, 'email', None)} phone={getattr(c, 'phone', None)}",
    )


def test_upload_zip_unauthenticated() -> None:
    """Sans UPLOAD_API_KEY ni ALLOW_ANONYMOUS_UPLOAD, l'upload anonyme est refusÃ© (sÃ©curisÃ© par dÃ©faut)."""
    c = make_client()
    buf = make_sample_zip()
    r = c.post(
        "/upload",
        data={"client_name": "Anonyme"},
        files={"file": ("intervention_anonyme.zip", buf, "application/zip")},
        follow_redirects=False,
    )
    record("POST /upload sans auth -> refusÃ© (401)", r.status_code == 401, f"status={r.status_code}")


def test_upload_zip_anonymous_allowed_when_opted_in() -> None:
    """Avec ALLOW_ANONYMOUS_UPLOAD=true, l'upload anonyme reste possible (usage local/dev)."""
    os.environ["ALLOW_ANONYMOUS_UPLOAD"] = "true"
    try:
        c = make_client()
        buf = make_sample_zip()
        r = c.post(
            "/upload",
            data={"client_name": "Anonyme AutorisÃ©"},
            files={"file": ("intervention_anonyme2.zip", buf, "application/zip")},
            follow_redirects=False,
        )
        record("POST /upload anonyme avec opt-in -> autorisÃ© (303)", r.status_code == 303, f"status={r.status_code}")
    finally:
        os.environ.pop("ALLOW_ANONYMOUS_UPLOAD", None)


def test_downloads_after_upload() -> None:
    r = client.get("/")
    if "Client ZIP Test" not in r.text:
        record("TÃ©lÃ©chargements intervention", False, "intervention importÃ©e introuvable")
        return
    # Trouver l'intervention via la page
    from app.database import SessionLocal
    from app.models import Intervention
    from sqlalchemy import select

    with SessionLocal() as session:
        intervention = session.scalars(
            select(Intervention).where(Intervention.title.contains("intervention_test")).order_by(Intervention.id.desc())
        ).first()
        if not intervention:
            intervention = session.scalars(select(Intervention).order_by(Intervention.id.desc())).first()
    if not intervention:
        record("TÃ©lÃ©chargements intervention", False, "aucune intervention en base")
        return

    iid = intervention.id
    r_report = client.get(f"/intervention/{iid}/download/report")
    r_manifest = client.get(f"/intervention/{iid}/download/manifest")
    r_zip = client.get(f"/intervention/{iid}/download/zip")
    record("GET download/report", r_report.status_code == 200 and "Rapport test" in r_report.text)
    record("GET download/manifest", r_manifest.status_code == 200)
    record("GET download/zip", r_zip.status_code == 200 and r_zip.headers.get("content-type", "").startswith("application/zip"))


def test_delete_requires_admin() -> None:
    from app.database import SessionLocal
    from app.models import Client
    from sqlalchemy import select

    with SessionLocal() as session:
        c = session.scalars(select(Client).where(Client.name == "Client Test")).first()
        if not c:
            record("DELETE client admin", False, "client test introuvable")
            return
        cid = c.id
    r = client.post(f"/delete/client/{cid}", follow_redirects=False)
    record("POST /delete/client admin", r.status_code == 303, f"status={r.status_code}")


def test_invalid_login() -> None:
    c = make_client()
    r = c.post("/login", data={"username": "admin", "password": "wrongpassword"})
    record("login mot de passe invalide", r.status_code == 200 and "incorrect" in r.text.lower())


def test_v10_pages() -> None:
    r = client.get("/quotes")
    record("GET /quotes", r.status_code == 200 and "Devis" in r.text)
    r = client.get("/settings")
    record("GET /settings", r.status_code == 200 and "Paramètres" in r.text)
    r = client.get("/export/interventions.csv")
    record("GET /export CSV", r.status_code == 200 and "text/csv" in r.headers.get("content-type", ""))


def test_intervention_detail() -> None:
    from app.database import SessionLocal
    from app.models import Intervention
    from sqlalchemy import select
    with SessionLocal() as session:
        intervention = session.scalars(select(Intervention).order_by(Intervention.id.desc())).first()
    if not intervention:
        record("GET /intervention detail", False, "aucune intervention")
        return
    r = client.get(f"/intervention/{intervention.id}")
    record("GET /intervention detail", r.status_code == 200 and "Téléchargements" in r.text)


def test_create_quote() -> None:
    from app.database import SessionLocal
    from app.models import Intervention
    from sqlalchemy import select
    with SessionLocal() as session:
        intervention = session.scalars(select(Intervention).order_by(Intervention.id.desc())).first()
    if not intervention:
        record("POST /quotes", False, "pas d'intervention")
        return
    r = client.post("/quotes", data={
        "intervention_id": intervention.id,
        "amount": "50",
        "description": "Test devis",
        "status": "draft",
    }, follow_redirects=False)
    record("POST /quotes", r.status_code == 303)


def test_comptabilite_page() -> None:
    r = client.get("/comptabilite")
    record("GET /comptabilite", r.status_code == 200 and "Comptabilité" in r.text, f"status={r.status_code}")


def test_comptabilite_requires_admin() -> None:
    c = make_client()
    r = c.get("/comptabilite", follow_redirects=False)
    record("GET /comptabilite sans auth -> redirect", r.status_code == 303)


def test_export_comptable_xlsx() -> None:
    r = client.get("/export/comptable.xlsx")
    record(
        "GET /export/comptable.xlsx",
        r.status_code == 200 and "spreadsheetml" in r.headers.get("content-type", ""),
        r.headers.get("content-type", ""),
    )


def test_backup_rotation_unit() -> None:
    """_rotate_backups doit conserver uniquement les BACKUP_RETENTION_COUNT
    fichiers les plus rÃ©cents (rescuegrid_*), quel que soit le moteur (SQLite/PG)."""
    from app import backup as backup_module

    with tempfile.TemporaryDirectory() as tmp:
        backups_dir = Path(tmp) / "backups"
        backups_dir.mkdir()
        original_retention = backup_module.BACKUP_RETENTION_COUNT
        backup_module.BACKUP_RETENTION_COUNT = 3
        try:
            now = time.time()
            for i in range(5):
                f = backups_dir / f"rescuegrid_2026010{i}_000000.db"
                f.write_text("dummy")
                mtime = now - (5 - i)
                os.utime(f, (mtime, mtime))
            backup_module._rotate_backups(backups_dir)
            remaining = sorted(p.name for p in backups_dir.iterdir())
            record(
                "Rotation sauvegardes (retention=3 sur 5 fichiers)",
                len(remaining) == 3,
                f"restants={remaining}",
            )
        finally:
            backup_module.BACKUP_RETENTION_COUNT = original_retention


def test_backup_perform_and_rotate_sqlite() -> None:
    """perform_backup_and_rotate doit copier le fichier SQLite et crÃ©er une
    entrÃ©e listable par list_backups() â€” testÃ© avec des dossiers isolÃ©s
    (aucun impact sur la vraie base de dÃ©veloppement)."""
    import sqlite3

    from app import backup as backup_module

    with tempfile.TemporaryDirectory() as tmp:
        base_dir = Path(tmp)
        storage_dir = Path(tmp) / "storage"
        storage_dir.mkdir()
        db_path = base_dir / "rescuegrid.db"
        conn = sqlite3.connect(db_path)
        try:
            conn.execute("CREATE TABLE ping (id INTEGER PRIMARY KEY)")
            conn.execute("INSERT INTO ping (id) VALUES (1)")
            conn.commit()
        finally:
            conn.close()
        dest = backup_module.perform_backup_and_rotate(base_dir, storage_dir)
        backups = backup_module.list_backups(storage_dir)
        verify = sqlite3.connect(dest)
        try:
            row = verify.execute("SELECT id FROM ping").fetchone()
        finally:
            verify.close()
        ok = (
            dest.exists()
            and dest.name.startswith("rescuegrid_")
            and len(backups) == 1
            and row == (1,)
        )
        record("perform_backup_and_rotate (SQLite, dossiers isolÃ©s)", ok, str(dest))


def test_backup_history_requires_admin() -> None:
    c = make_client()
    r = c.get("/backup/history", follow_redirects=False)
    record("GET /backup/history sans auth -> redirect", r.status_code == 303, f"status={r.status_code}")


def test_backup_history_page() -> None:
    r = client.get("/backup/history")
    record(
        "GET /backup/history (admin)",
        r.status_code == 200 and "sauvegardes planifiées" in r.text.lower(),
        f"status={r.status_code}",
    )


def test_backup_run_requires_admin() -> None:
    c = make_client()
    r = c.post("/backup/run", follow_redirects=False)
    record("POST /backup/run sans auth -> redirect", r.status_code == 303, f"status={r.status_code}")


def test_backup_run_manual() -> None:
    """Le dÃ©clenchement manuel ne doit jamais planter (500), qu'il rÃ©ussisse
    (rescuegrid.db prÃ©sent en local) ou Ã©choue proprement avec un message
    d'erreur (absent sur une machine de test fraÃ®che)."""
    r = client.post("/backup/run", follow_redirects=False)
    ok = r.status_code == 303 and (r.headers.get("location") or "").startswith("/backup/history")
    record("POST /backup/run (admin)", ok, f"status={r.status_code} location={r.headers.get('location')}")


def test_planning_crud() -> None:
    from datetime import datetime, timedelta, timezone
    start = (datetime.now(timezone.utc) + timedelta(days=2)).strftime("%Y-%m-%dT%H:%M")
    r = client.post("/planning", data={
        "title": "RDV Test Planning",
        "client_id": "0",
        "intervention_id": "0",
        "technician_id": "0",
        "start_at": start,
    }, follow_redirects=False)
    record("POST /planning crÃ©ation RDV", r.status_code == 303, f"status={r.status_code}")

    from app.database import SessionLocal
    from app.models import Appointment
    from sqlalchemy import select
    with SessionLocal() as session:
        appointment = session.scalars(
            select(Appointment).where(Appointment.title == "RDV Test Planning").order_by(Appointment.id.desc())
        ).first()
    if not appointment:
        record("GET /planning liste", False, "rendez-vous introuvable aprÃ¨s crÃ©ation")
        return
    aid = appointment.id

    r = client.get("/planning?range_filter=all")
    record("GET /planning liste", r.status_code == 200 and "RDV Test Planning" in r.text, f"status={r.status_code}")

    r = client.post(f"/planning/{aid}/status", data={"status": "confirmed"}, follow_redirects=False)
    record("POST /planning/{id}/status", r.status_code == 303, f"status={r.status_code}")

    r = client.post(f"/delete/appointment/{aid}", follow_redirects=False)
    record("POST /delete/appointment admin", r.status_code == 303, f"status={r.status_code}")


def test_planning_requires_auth() -> None:
    c = make_client()
    r = c.get("/planning", follow_redirects=False)
    record("GET /planning sans auth -> redirect", r.status_code == 303)


def test_relances_page() -> None:
    r = client.get("/relances")
    record("GET /relances", r.status_code == 200 and "Relances" in r.text, f"status={r.status_code}")


def test_reminders_flow() -> None:
    from datetime import datetime, timedelta, timezone
    from app.database import SessionLocal
    from app.models import Client, Intervention, Invoice, Quote
    from sqlalchemy import select

    with SessionLocal() as session:
        client_row = Client(name="Client Relances", email="relances@example.com")
        session.add(client_row)
        session.commit()
        intervention = Intervention(client_id=client_row.id, title="Intervention relances")
        session.add(intervention)
        session.commit()
        past = datetime.now(timezone.utc) - timedelta(days=5)
        quote = Quote(
            intervention_id=intervention.id, client_id=client_row.id, quote_number="DEV-TESTRELANCE-0001",
            amount=100.0, tax=0.0, total=100.0, status="sent", valid_until=past,
        )
        invoice = Invoice(
            intervention_id=intervention.id, client_id=client_row.id, invoice_number="INV-TESTRELANCE-0001",
            amount=150.0, tax=0.0, total=150.0, status="issued", due_date=past,
        )
        session.add_all([quote, invoice])
        session.commit()
        quote_id, invoice_id = quote.id, invoice.id

    r = client.get("/relances")
    record(
        "GET /relances liste devis/factures en retard",
        r.status_code == 200 and "DEV-TESTRELANCE-0001" in r.text and "INV-TESTRELANCE-0001" in r.text,
    )

    r = client.post(f"/quote/{quote_id}/remind", follow_redirects=False)
    record("POST /quote/{id}/remind", r.status_code == 303, f"status={r.status_code} location={r.headers.get('location')}")

    r = client.post(f"/invoice/{invoice_id}/remind", follow_redirects=False)
    record("POST /invoice/{id}/remind", r.status_code == 303, f"status={r.status_code} location={r.headers.get('location')}")


def test_client_portal_flow() -> None:
    from app.auth import hash_password
    from app.database import SessionLocal
    from app.models import Client, ClientAccount
    from sqlalchemy import select

    r = client.post("/clients", data={"name": "Client Portail Test", "email": "portail@example.com"}, follow_redirects=False)
    record("POST /clients (client portail)", r.status_code == 303)

    with SessionLocal() as session:
        client_row = session.scalars(select(Client).where(Client.name == "Client Portail Test")).first()
    if not client_row:
        record("Setup client portail", False, "client introuvable")
        return
    client_id = client_row.id

    r = client.post(f"/client/{client_id}/portal/enable", data={"email": "portail@example.com"}, follow_redirects=False)
    record("POST /client/{id}/portal/enable (admin)", r.status_code == 303, f"status={r.status_code}")

    # Le mot de passe temporaire est envoyÃ© par email (SMTP dÃ©sactivÃ© en test) :
    # on le fixe directement en base pour tester le flux de connexion complet.
    known_password = "PortailTest2026!"
    with SessionLocal() as session:
        account = session.scalars(select(ClientAccount).where(ClientAccount.client_id == client_id)).first()
        if not account:
            record("ClientAccount crÃ©Ã©", False, "aucun compte espace client crÃ©Ã©")
            return
        account.hashed_password = hash_password(known_password)
        session.commit()
    record("ClientAccount crÃ©Ã©", True)

    r = client.get("/client/login")
    record("GET /client/login", r.status_code == 200 and "Espace client" in r.text)

    anon = make_client()
    r = anon.post("/client/login", data={"email": "portail@example.com", "password": "wrong-password"})
    record("POST /client/login mot de passe invalide", r.status_code == 200 and "incorrect" in r.text.lower())

    r = anon.post("/client/login", data={"email": "portail@example.com", "password": known_password}, follow_redirects=False)
    record("POST /client/login rÃ©ussi", r.status_code == 303 and "client_token" in r.cookies, f"status={r.status_code}")

    r = anon.get("/client/portal")
    record("GET /client/portal authentifiÃ©", r.status_code == 200 and "Client Portail Test" in r.text, f"status={r.status_code}")

    r = client.post(f"/client/{client_id}/portal/disable", follow_redirects=False)
    record("POST /client/{id}/portal/disable (admin)", r.status_code == 303)

    r = anon.get("/client/portal", follow_redirects=False)
    record("GET /client/portal aprÃ¨s dÃ©sactivation -> redirect login", r.status_code == 303 and r.headers.get("location") == "/client/login")


def test_client_portal_requires_auth() -> None:
    c = make_client()
    r = c.get("/client/portal", follow_redirects=False)
    record("GET /client/portal sans auth -> redirect", r.status_code == 303 and r.headers.get("location") == "/client/login")


# â”€â”€ Tests revue de sÃ©curitÃ© (auto-gÃ©nÃ©rÃ©s lors de la remÃ©diation) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def _create_technician_and_login() -> "TestClient":
    """CrÃ©e un compte technicien (role != admin) et retourne un client authentifiÃ©
    en tant que ce compte â€” utilisÃ© pour vÃ©rifier qu'un non-admin ne peut pas
    accÃ©der aux routes rÃ©servÃ©es Ã  l'administrateur (contrairement Ã  un test
    "sans auth", qui ne distingue pas rÃ´le insuffisant de absence de session)."""
    from app.auth import hash_password
    from app.database import SessionLocal
    from app.models import User
    from sqlalchemy import select

    with SessionLocal() as session:
        existing = session.scalars(select(User).where(User.username == "tech1")).first()
        if not existing:
            session.add(User(
                username="tech1", hashed_password=hash_password("techpassword2026"),
                full_name="Technicien Test", role="technicien", email="tech1@rescuegrid.local",
            ))
            session.commit()
    tech_client = make_client()
    tech_client.post("/login", data={"username": "tech1", "password": "techpassword2026"})
    return tech_client


def test_backup_database_requires_admin() -> None:
    c = make_client()
    r = c.get("/backup/database", follow_redirects=False)
    record("GET /backup/database sans auth -> 401", r.status_code == 401, f"status={r.status_code}")

    tech = _create_technician_and_login()
    r = tech.get("/backup/database", follow_redirects=False)
    record("GET /backup/database technicien -> 401 (admin requis)", r.status_code == 401, f"status={r.status_code}")

    r = client.get("/backup/database", follow_redirects=False)
    record(
        "GET /backup/database admin -> autorisÃ© (200 ou 404 si SQLite absent)",
        r.status_code in (200, 404),
        f"status={r.status_code}",
    )


def test_upload_logo_requires_admin() -> None:
    tech = _create_technician_and_login()
    fake_png = io.BytesIO(b"\x89PNG\r\n\x1a\n" + b"0" * 32)
    r = tech.post("/upload-logo", files={"file": ("logo.png", fake_png, "image/png")}, follow_redirects=False)
    record("POST /upload-logo technicien -> refusÃ© (redirect /)", r.status_code == 303 and r.headers.get("location") == "/", f"status={r.status_code}")


def test_intervention_label_escapes_xss() -> None:
    """Un nom de client contenant du HTML/JS ne doit jamais Ãªtre injectÃ© tel
    quel dans l'Ã©tiquette imprimable (XSS stockÃ©e corrigÃ©e lors de la revue
    de sÃ©curitÃ©) : le nom doit apparaÃ®tre Ã©chappÃ© (&lt;script&gt;)."""
    from app.database import SessionLocal
    from app.models import Client, Intervention
    from sqlalchemy import select

    xss_name = "<script>alert(1)</script>"
    with SessionLocal() as session:
        c = Client(name=xss_name)
        session.add(c)
        session.commit()
        intervention = Intervention(client_id=c.id, title="Intervention XSS test", machine_name="PC-XSS")
        session.add(intervention)
        session.commit()
        iid = intervention.id

    r = client.get(f"/intervention/{iid}/label")
    ok = r.status_code == 200 and "<script>alert(1)</script>" not in r.text and "&lt;script&gt;" in r.text
    record("GET /intervention/{id}/label Ã©chappe le nom client (anti-XSS)", ok, f"status={r.status_code}")


def test_safe_extract_zip_rejects_symlink() -> None:
    """Une entrÃ©e ZIP encodant un lien symbolique Unix doit Ãªtre rejetÃ©e mÃªme
    si son propre chemin dans l'archive est valide (variante Zip Slip via
    symlink, corrigÃ©e lors de la revue de sÃ©curitÃ©)."""
    import stat
    import zipfile as _zipfile

    with tempfile.TemporaryDirectory() as tmp:
        dest = Path(tmp)
        zip_path = dest / "symlink.zip"
        with _zipfile.ZipFile(zip_path, "w") as zf:
            info = _zipfile.ZipInfo("innocuous_link")
            info.external_attr = (stat.S_IFLNK | 0o777) << 16
            zf.writestr(info, "/etc/passwd")
        try:
            safe_extract_zip(zip_path, dest / "out")
            record("safe_extract_zip rejette les liens symboliques", False, "devrait lever une exception")
        except HTTPException as exc:
            record("safe_extract_zip rejette les liens symboliques", exc.status_code == 400, f"status={exc.status_code}")


def test_upload_rate_limit() -> None:
    """Un enchaînement de tentatives /upload avec une mauvaise clé API doit
    finir par être bloqué (429), pour freiner le brute-force de UPLOAD_API_KEY."""
    from app.routes import interventions as interventions_module
    from app.rate_limit import clear_bucket

    os.environ["UPLOAD_API_KEY"] = "correct-key-for-rate-limit-test"
    clear_bucket("upload_auth:testclient")
    # L'IP vue par TestClient est typiquement "testclient"
    for ip in ("testclient", "127.0.0.1", "unknown"):
        clear_bucket(f"upload_auth:{ip}")
    try:
        c = make_client()
        last_status = None
        for _ in range(interventions_module.UPLOAD_RATE_LIMIT_COUNT + 2):
            buf = make_sample_zip()
            r = c.post(
                "/upload",
                data={"client_name": "RateLimitTest", "upload_key": "wrong-key"},
                files={"file": ("rl.zip", buf, "application/zip")},
                follow_redirects=False,
            )
            last_status = r.status_code
        record("POST /upload rate limit après échecs répétés -> 429", last_status == 429, f"status={last_status}")
    finally:
        os.environ.pop("UPLOAD_API_KEY", None)
        for ip in ("testclient", "127.0.0.1", "unknown"):
            clear_bucket(f"upload_auth:{ip}")


def test_upload_rejects_non_zip_content() -> None:
    """Un fichier renommÃ© .zip mais dont le contenu n'est pas une archive ZIP
    (signature magique absente) doit Ãªtre rejetÃ© (400) plutÃ´t qu'extrait."""
    fake = io.BytesIO(b"ceci n'est pas un zip")
    r = client.post(
        "/upload",
        data={"client_name": "FauxZip"},
        files={"file": ("faux.zip", fake, "application/zip")},
        follow_redirects=False,
    )
    record("POST /upload contenu non-ZIP -> 400", r.status_code == 400, f"status={r.status_code}")


def test_security_headers_present() -> None:
    r = client.get("/health")
    ok = (
        r.headers.get("X-Frame-Options") == "DENY"
        and r.headers.get("X-Content-Type-Options") == "nosniff"
        and "Content-Security-Policy" in r.headers
    )
    record("En-tÃªtes de sÃ©curitÃ© HTTP prÃ©sents", ok, str(dict(r.headers)))


def test_cookie_not_secure_by_default() -> None:
    """COOKIE_SECURE=false par dÃ©faut (dev local http://) : le cookie de
    session ne doit pas porter l'attribut Secure, sans quoi aucun navigateur
    ne le renverrait en http://localhost. Le compte admin Ã©tant enrÃ´lÃ© en 2FA
    (voir login()), il faut complÃ©ter la vÃ©rification TOTP pour obtenir le
    cookie access_token final."""
    c = make_client()
    r = c.post("/login", data={"username": "admin", "password": "testadmin2026"}, follow_redirects=False)
    set_cookie = r.headers.get("set-cookie", "")
    record("POST /login admin dÃ©jÃ  enrÃ´lÃ© -> redirect /2fa/verify", r.status_code == 303 and r.headers.get("location") == "/2fa/verify")
    r2 = c.post("/2fa/verify", data={"code": pyotp.TOTP(ADMIN_TOTP_SECRET).now()}, follow_redirects=False)
    set_cookie = r2.headers.get("set-cookie", "")
    record(
        "Cookie access_token sans Secure quand COOKIE_SECURE=false",
        "access_token" in set_cookie and "secure" not in set_cookie.lower(),
        set_cookie,
    )


def test_invoice_invalid_intervention_id() -> None:
    """POST /invoices avec un intervention_id inexistant doit renvoyer une
    erreur claire (400) plutÃ´t qu'un 500 (IntegrityError sous PostgreSQL)."""
    r = client.post("/invoices", data={"intervention_id": "999999", "amount": "50"}, follow_redirects=False)
    record("POST /invoices intervention_id invalide -> 400", r.status_code == 400, f"status={r.status_code}")


# â”€â”€ Tests Stripe (paiement en ligne) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def _create_test_invoice(notes: str, status: str = "issued") -> "int | None":
    from app.database import SessionLocal
    from app.models import Client, Intervention, Invoice
    from sqlalchemy import select

    with SessionLocal() as session:
        client_row = Client(name=f"Client Stripe {notes}", email="stripe-test@example.com")
        session.add(client_row)
        session.commit()
        intervention = Intervention(client_id=client_row.id, title=f"Intervention {notes}")
        session.add(intervention)
        session.commit()
        intervention_id = intervention.id

    r = client.post("/invoices", data={
        "intervention_id": intervention_id, "amount": "80", "notes": notes, "status": status,
    }, follow_redirects=False)
    if r.status_code != 303:
        return None
    with SessionLocal() as session:
        invoice = session.scalars(
            select(Invoice).where(Invoice.notes == notes).order_by(Invoice.id.desc())
        ).first()
        return invoice.id if invoice else None


def test_invoice_pdf_without_stripe_key() -> None:
    """Sans STRIPE_SECRET_KEY (comportement par dÃ©faut), le PDF facture doit
    continuer Ã  se gÃ©nÃ©rer sans lien de paiement et sans jamais planter."""
    invoice_id = _create_test_invoice("Facture test sans cle Stripe")
    if not invoice_id:
        record("GET /invoice/{id}/pdf sans clÃ© Stripe", False, "facture introuvable")
        return
    r = client.get(f"/invoice/{invoice_id}/pdf")
    ok = r.status_code == 200 and "payer en ligne" not in r.text.lower()
    record("GET /invoice/{id}/pdf sans clÃ© Stripe -> pas de lien de paiement, pas de crash", ok, f"status={r.status_code}")


def test_stripe_webhook_invalid_signature_rejected() -> None:
    """Sans STRIPE_WEBHOOK_SECRET configurÃ© (ou avec une signature invalide),
    le webhook doit Ãªtre rejetÃ© (400) sans jamais modifier de facture."""
    c = make_client()
    r = c.post(
        "/stripe/webhook",
        content=b'{"type": "checkout.session.completed", "data": {"object": {"metadata": {}}}}',
        headers={"stripe-signature": "invalid", "content-type": "application/json"},
    )
    record("POST /stripe/webhook signature invalide -> 400", r.status_code == 400, f"status={r.status_code}")


def test_ensure_payment_link_skips_paid_invoice() -> None:
    """ensure_payment_link ne doit jamais gÃ©nÃ©rer de lien pour une facture dÃ©jÃ 
    payÃ©e ou annulÃ©e, mÃªme si Stripe est configurÃ© (aucun appel rÃ©seau requis
    pour cette vÃ©rification : elle intervient avant toute crÃ©ation de Session)."""
    from app import stripe_payments
    from app.database import SessionLocal
    from app.models import Invoice

    original_key = stripe_payments.STRIPE_SECRET_KEY
    stripe_payments.STRIPE_SECRET_KEY = "sk_test_fake_for_unit_test"
    try:
        with SessionLocal() as session:
            invoice = Invoice(
                invoice_number="INV-TESTSTRIPE-0001", amount=42.0, tax=0.0, total=42.0, status="paid",
            )
            session.add(invoice)
            session.commit()
            link = stripe_payments.ensure_payment_link(session, invoice)
        record("ensure_payment_link ignore une facture payÃ©e", link is None, f"link={link}")
    finally:
        stripe_payments.STRIPE_SECRET_KEY = original_key


def test_ensure_payment_link_disabled_without_key() -> None:
    """Sans STRIPE_SECRET_KEY, ensure_payment_link retourne toujours None, quel
    que soit le statut de la facture (comportement par dÃ©faut du projet)."""
    from app import stripe_payments
    from app.database import SessionLocal
    from app.models import Invoice

    record("stripe_enabled() est faux par dÃ©faut", stripe_payments.stripe_enabled() is False, f"key={stripe_payments.STRIPE_SECRET_KEY!r}")
    with SessionLocal() as session:
        invoice = Invoice(
            invoice_number="INV-TESTSTRIPE-0002", amount=10.0, tax=0.0, total=10.0, status="issued",
        )
        session.add(invoice)
        session.commit()
        link = stripe_payments.ensure_payment_link(session, invoice)
    record("ensure_payment_link() sans clÃ© -> None", link is None, f"link={link}")


# â”€â”€ Tests relances automatiques (scheduler) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def test_reminder_scheduler_disabled_by_default() -> None:
    """Sans REMINDER_SCHEDULE_ENABLED=true, start_reminder_scheduler() ne doit
    jamais dÃ©marrer de tÃ¢che de fond (relances 100% manuelles par dÃ©faut)."""
    from app import reminders_scheduler

    record(
        "REMINDER_SCHEDULE_ENABLED dÃ©sactivÃ© par dÃ©faut",
        reminders_scheduler.REMINDER_SCHEDULE_ENABLED is False,
        f"enabled={reminders_scheduler.REMINDER_SCHEDULE_ENABLED}",
    )
    task = reminders_scheduler.start_reminder_scheduler()
    record("start_reminder_scheduler() retourne None par dÃ©faut", task is None, f"task={task}")


def test_reminder_cooldown_skips_recent() -> None:
    """Un Reminder envoyÃ© il y a 2 jours (< REMINDER_COOLDOWN_DAYS) doit
    empÃªcher un nouveau renvoi automatique."""
    from app import reminders_scheduler
    from datetime import datetime, timedelta, timezone

    recent = datetime.now(timezone.utc) - timedelta(days=2)
    ok = reminders_scheduler._is_in_cooldown(recent, reminders_scheduler.REMINDER_COOLDOWN_DAYS)
    record("Cooldown relance : envoyÃ© il y a 2j -> pas de renvoi (7j)", ok is True, f"in_cooldown={ok}")


def test_reminder_cooldown_allows_after_delay() -> None:
    """Un Reminder envoyÃ© il y a 8 jours (> REMINDER_COOLDOWN_DAYS=7) doit
    autoriser un nouveau renvoi automatique."""
    from app import reminders_scheduler
    from datetime import datetime, timedelta, timezone

    old = datetime.now(timezone.utc) - timedelta(days=8)
    ok = reminders_scheduler._is_in_cooldown(old, reminders_scheduler.REMINDER_COOLDOWN_DAYS)
    record("Cooldown relance : envoyÃ© il y a 8j -> renvoi autorisÃ© (7j)", ok is False, f"in_cooldown={ok}")


def test_reminder_cooldown_no_previous_reminder() -> None:
    """Sans relance prÃ©alable (last_sent_at=None), le cooldown ne doit jamais
    bloquer le premier envoi automatique."""
    from app import reminders_scheduler

    ok = reminders_scheduler._is_in_cooldown(None, reminders_scheduler.REMINDER_COOLDOWN_DAYS)
    record("Cooldown relance : aucune relance prÃ©cÃ©dente -> renvoi autorisÃ©", ok is False, f"in_cooldown={ok}")


# â”€â”€ Tests 2FA (TOTP obligatoire pour le rÃ´le admin) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def _create_second_admin() -> tuple[str, str]:
    from app.auth import hash_password
    from app.database import SessionLocal
    from app.models import User
    from sqlalchemy import select

    username, password = "admin2fa", "admin2fapassword2026"
    with SessionLocal() as session:
        existing = session.scalars(select(User).where(User.username == username)).first()
        if not existing:
            session.add(User(
                username=username, hashed_password=hash_password(password),
                full_name="Admin 2FA Test", role="admin", email="admin2fa@rescuegrid.local",
            ))
            session.commit()
    return username, password


def test_2fa_forced_on_first_admin_login() -> None:
    """Un compte admin sans 2FA active doit Ãªtre redirigÃ© vers /2fa/setup aprÃ¨s
    un mot de passe correct, sans jamais recevoir de cookie access_token."""
    username, password = _create_second_admin()
    c = make_client()
    r = c.post("/login", data={"username": username, "password": password}, follow_redirects=False)
    record(
        "Admin sans 2FA -> redirect /2fa/setup (pas d'accÃ¨s direct)",
        r.status_code == 303 and r.headers.get("location") == "/2fa/setup" and "access_token" not in r.cookies,
        f"status={r.status_code} location={r.headers.get('location')}",
    )

    # Tant que le code n'est pas confirmÃ©, aucune route protÃ©gÃ©e n'est accessible.
    r2 = c.get("/", follow_redirects=False)
    record("AccÃ¨s dashboard bloquÃ© pendant l'enrÃ´lement 2FA en attente", r2.status_code == 303 and r2.headers.get("location") == "/login")


def test_2fa_setup_wrong_code_rejected() -> None:
    username, password = _create_second_admin()
    c = make_client()
    c.post("/login", data={"username": username, "password": password}, follow_redirects=False)
    c.get("/2fa/setup")  # fige le secret dans le cookie pending_2fa (voir two_fa_setup_page)
    r = c.post("/2fa/setup", data={"code": "000000"}, follow_redirects=False)
    record("Code TOTP invalide Ã  l'enrÃ´lement -> refusÃ©", r.status_code == 200 and "invalide" in r.text.lower(), f"status={r.status_code}")
    record("access_token toujours absent aprÃ¨s code invalide", "access_token" not in r.cookies)


def test_2fa_full_enrollment_and_login_cycle() -> None:
    """EnrÃ´lement complet (code correct) puis nouvelle connexion (code TOTP
    valide) et vÃ©rification qu'un code de secours n'est utilisable qu'une fois."""
    username, password = _create_second_admin()
    c = make_client()
    c.post("/login", data={"username": username, "password": password}, follow_redirects=False)
    setup_page = c.get("/2fa/setup")
    secret = _extract_totp_secret(setup_page.text)
    record("Secret TOTP prÃ©sent sur la page d'enrÃ´lement", bool(secret))

    r = c.post("/2fa/setup", data={"code": pyotp.TOTP(secret).now()}, follow_redirects=False)
    record("Code TOTP correct -> codes de secours affichÃ©s", r.status_code == 200 and "codes de secours" in r.text.lower(), f"status={r.status_code}")
    recovery_codes = re.findall(r">([0-9A-F]{4}-[0-9A-F]{4})<", r.text)
    record("8 codes de secours gÃ©nÃ©rÃ©s", len(recovery_codes) == 8, f"count={len(recovery_codes)}")

    r2 = c.post("/2fa/setup/continue", follow_redirects=False)
    record("Finalisation enrÃ´lement -> access_token Ã©mis", r2.status_code == 303 and "access_token" in r2.cookies)

    # Nouvelle session : le prochain login doit demander /2fa/verify (plus /2fa/setup).
    c2 = make_client()
    r3 = c2.post("/login", data={"username": username, "password": password}, follow_redirects=False)
    record("Admin dÃ©jÃ  enrÃ´lÃ© -> redirect /2fa/verify", r3.status_code == 303 and r3.headers.get("location") == "/2fa/verify")

    r4 = c2.post("/2fa/verify", data={"code": "000000"}, follow_redirects=False)
    record("Code TOTP invalide Ã  la vÃ©rification -> refusÃ©", "access_token" not in r4.cookies and "invalide" in r4.text.lower())

    r5 = c2.post("/2fa/verify", data={"code": pyotp.TOTP(secret).now()}, follow_redirects=False)
    record("Code TOTP correct Ã  la vÃ©rification -> access_token Ã©mis", r5.status_code == 303 and "access_token" in r5.cookies)

    # Code de secours : utilisable une fois, puis rejetÃ© Ã  la seconde tentative.
    c3 = make_client()
    c3.post("/login", data={"username": username, "password": password}, follow_redirects=False)
    code_to_use = recovery_codes[0]
    r6 = c3.post("/2fa/verify", data={"code": code_to_use}, follow_redirects=False)
    record("Code de secours valide -> access_token Ã©mis", r6.status_code == 303 and "access_token" in r6.cookies)

    c4 = make_client()
    c4.post("/login", data={"username": username, "password": password}, follow_redirects=False)
    r7 = c4.post("/2fa/verify", data={"code": code_to_use}, follow_redirects=False)
    record("Code de secours dÃ©jÃ  utilisÃ© -> refusÃ© Ã  la 2e tentative", "access_token" not in r7.cookies)


def test_2fa_not_required_for_technician() -> None:
    """La 2FA n'est obligatoire que pour le rÃ´le admin (voir choix utilisateur) :
    un compte technicien reÃ§oit directement son access_token."""
    tech_client = _create_technician_and_login()
    r = tech_client.get("/", follow_redirects=False)
    record("Technicien accÃ¨de au dashboard sans 2FA", r.status_code == 200)


def main() -> int:
    print("=== Tests Restor-PC RescueGrid ===\n")
    test_health()
    test_login_page()
    test_dashboard_requires_auth()
    test_create_client_requires_auth()
    test_storage_requires_auth()
    test_export_requires_auth()
    login()
    test_authenticated_dashboard()
    test_create_client_authenticated()
    test_search()
    test_export_authenticated()
    test_api_stats()
    test_sanitize_filename()
    test_safe_extract_zip_zipslip()
    test_upload_zip_authenticated()
    test_upload_metadata_from_inventory()
    test_upload_creates_client_fiche()
    test_upload_zip_unauthenticated()
    test_upload_zip_anonymous_allowed_when_opted_in()
    test_downloads_after_upload()
    test_intervention_detail()
    test_v10_pages()
    test_create_quote()
    test_comptabilite_requires_admin()
    test_comptabilite_page()
    test_export_comptable_xlsx()
    test_backup_rotation_unit()
    test_backup_perform_and_rotate_sqlite()
    test_backup_history_requires_admin()
    test_backup_history_page()
    test_backup_run_requires_admin()
    test_backup_run_manual()
    test_planning_requires_auth()
    test_planning_crud()
    test_relances_page()
    test_reminders_flow()
    test_client_portal_requires_auth()
    test_client_portal_flow()
    test_delete_requires_admin()
    test_invalid_login()

    # Revue de sÃ©curitÃ©
    test_backup_database_requires_admin()
    test_upload_logo_requires_admin()
    test_intervention_label_escapes_xss()
    test_safe_extract_zip_rejects_symlink()
    test_upload_rate_limit()
    test_upload_rejects_non_zip_content()
    test_security_headers_present()
    test_cookie_not_secure_by_default()
    test_invoice_invalid_intervention_id()

    # Stripe (paiement en ligne)
    test_invoice_pdf_without_stripe_key()
    test_stripe_webhook_invalid_signature_rejected()
    test_ensure_payment_link_skips_paid_invoice()
    test_ensure_payment_link_disabled_without_key()

    # Relances automatiques (scheduler)
    test_reminder_scheduler_disabled_by_default()
    test_reminder_cooldown_skips_recent()
    test_reminder_cooldown_allows_after_delay()
    test_reminder_cooldown_no_previous_reminder()

    # 2FA (TOTP obligatoire pour le rÃ´le admin) â€” ordre important : ces tests
    # partagent le mÃªme compte "admin2fa" et dÃ©pendent de son Ã©tat 2FA au fil
    # de l'exÃ©cution (non enrÃ´lÃ© -> refus de code -> enrÃ´lement complet).
    test_2fa_forced_on_first_admin_login()
    test_2fa_setup_wrong_code_rejected()
    test_2fa_full_enrollment_and_login_cycle()
    test_2fa_not_required_for_technician()

    passed = sum(1 for _, ok, _ in results if ok)
    failed = sum(1 for _, ok, _ in results if not ok)
    print(f"\n=== RÃ©sultat: {passed} PASS, {failed} FAIL / {len(results)} tests ===")
    try:
        if TEST_DB.exists():
            TEST_DB.unlink()
    except PermissionError:
        print(f"(info) base test non supprimÃ©e: {TEST_DB}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())


"""Tests d'intégration Restor-PC RescueGrid — exécution autonome."""
from __future__ import annotations

import io
import json
import os
import sys
import tempfile
import zipfile
from pathlib import Path

# Backend root on path
BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))
os.chdir(BACKEND_DIR)

# Base de test isolée
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

client = TestClient(app)
results: list[tuple[str, bool, str]] = []


def record(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, ok, detail))
    status = "PASS" if ok else "FAIL"
    print(f"[{status}] {name}" + (f" — {detail}" if detail else ""))


def login() -> None:
    r = client.post("/login", data={"username": "admin", "password": "testadmin2026"}, follow_redirects=False)
    record("login admin", r.status_code == 303 and "access_token" in r.cookies, f"status={r.status_code}")


def test_health() -> None:
    r = client.get("/health")
    record("GET /health", r.status_code == 200 and r.json().get("status") == "ok", str(r.json()))


def test_login_page() -> None:
    r = client.get("/login")
    record("GET /login", r.status_code == 200 and "Restor-PC" in r.text, f"status={r.status_code}")


def test_dashboard_requires_auth() -> None:
    c = TestClient(app)
    r = c.get("/", follow_redirects=False)
    record("GET / sans auth -> redirect login", r.status_code == 303 and r.headers.get("location") == "/login")


def test_create_client_requires_auth() -> None:
    c = TestClient(app)
    r = c.post("/clients", data={"name": "Hacker"}, follow_redirects=False)
    record("POST /clients sans auth -> redirect", r.status_code == 303 and r.headers.get("location") == "/login")


def test_authenticated_dashboard() -> None:
    r = client.get("/")
    record("GET / dashboard authentifié", r.status_code == 200 and "Restor-PC RescueGrid" in r.text)


def test_create_client_authenticated() -> None:
    r = client.post("/clients", data={"name": "Client Test", "email": "test@example.com", "phone": "0600000000"}, follow_redirects=False)
    record("POST /clients authentifié", r.status_code == 303)


def test_search() -> None:
    r = client.get("/search?q=Client+Test")
    record("GET /search", r.status_code == 200 and "Client Test" in r.text)


def test_storage_requires_auth() -> None:
    c = TestClient(app)
    r = c.get("/storage/reports/fake.html", follow_redirects=False)
    record("GET /storage sans auth -> redirect", r.status_code == 303)


def test_export_requires_auth() -> None:
    c = TestClient(app)
    r = c.get("/export/interventions.xlsx", follow_redirects=False)
    record("GET /export sans auth -> redirect", r.status_code == 303)


def test_export_authenticated() -> None:
    r = client.get("/export/interventions.xlsx")
    record(
        "GET /export authentifié",
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
    record("POST /upload ZIP authentifié", r.status_code == 303, f"status={r.status_code}")


def test_upload_zip_unauthenticated() -> None:
    """Sans UPLOAD_API_KEY ni ALLOW_ANONYMOUS_UPLOAD, l'upload anonyme est refusé (sécurisé par défaut)."""
    c = TestClient(app)
    buf = make_sample_zip()
    r = c.post(
        "/upload",
        data={"client_name": "Anonyme"},
        files={"file": ("intervention_anonyme.zip", buf, "application/zip")},
        follow_redirects=False,
    )
    record("POST /upload sans auth -> refusé (401)", r.status_code == 401, f"status={r.status_code}")


def test_upload_zip_anonymous_allowed_when_opted_in() -> None:
    """Avec ALLOW_ANONYMOUS_UPLOAD=true, l'upload anonyme reste possible (usage local/dev)."""
    os.environ["ALLOW_ANONYMOUS_UPLOAD"] = "true"
    try:
        c = TestClient(app)
        buf = make_sample_zip()
        r = c.post(
            "/upload",
            data={"client_name": "Anonyme Autorisé"},
            files={"file": ("intervention_anonyme2.zip", buf, "application/zip")},
            follow_redirects=False,
        )
        record("POST /upload anonyme avec opt-in -> autorisé (303)", r.status_code == 303, f"status={r.status_code}")
    finally:
        os.environ.pop("ALLOW_ANONYMOUS_UPLOAD", None)


def test_downloads_after_upload() -> None:
    r = client.get("/")
    if "Client ZIP Test" not in r.text:
        record("Téléchargements intervention", False, "intervention importée introuvable")
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
        record("Téléchargements intervention", False, "aucune intervention en base")
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
    c = TestClient(app)
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
    c = TestClient(app)
    r = c.get("/comptabilite", follow_redirects=False)
    record("GET /comptabilite sans auth -> redirect", r.status_code == 303)


def test_export_comptable_xlsx() -> None:
    r = client.get("/export/comptable.xlsx")
    record(
        "GET /export/comptable.xlsx",
        r.status_code == 200 and "spreadsheetml" in r.headers.get("content-type", ""),
        r.headers.get("content-type", ""),
    )


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
    record("POST /planning création RDV", r.status_code == 303, f"status={r.status_code}")

    from app.database import SessionLocal
    from app.models import Appointment
    from sqlalchemy import select
    with SessionLocal() as session:
        appointment = session.scalars(
            select(Appointment).where(Appointment.title == "RDV Test Planning").order_by(Appointment.id.desc())
        ).first()
    if not appointment:
        record("GET /planning liste", False, "rendez-vous introuvable après création")
        return
    aid = appointment.id

    r = client.get("/planning?range_filter=all")
    record("GET /planning liste", r.status_code == 200 and "RDV Test Planning" in r.text, f"status={r.status_code}")

    r = client.post(f"/planning/{aid}/status", data={"status": "confirmed"}, follow_redirects=False)
    record("POST /planning/{id}/status", r.status_code == 303, f"status={r.status_code}")

    r = client.post(f"/delete/appointment/{aid}", follow_redirects=False)
    record("POST /delete/appointment admin", r.status_code == 303, f"status={r.status_code}")


def test_planning_requires_auth() -> None:
    c = TestClient(app)
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

    # Le mot de passe temporaire est envoyé par email (SMTP désactivé en test) :
    # on le fixe directement en base pour tester le flux de connexion complet.
    known_password = "PortailTest2026!"
    with SessionLocal() as session:
        account = session.scalars(select(ClientAccount).where(ClientAccount.client_id == client_id)).first()
        if not account:
            record("ClientAccount créé", False, "aucun compte espace client créé")
            return
        account.hashed_password = hash_password(known_password)
        session.commit()
    record("ClientAccount créé", True)

    r = client.get("/client/login")
    record("GET /client/login", r.status_code == 200 and "Espace client" in r.text)

    anon = TestClient(app)
    r = anon.post("/client/login", data={"email": "portail@example.com", "password": "wrong-password"})
    record("POST /client/login mot de passe invalide", r.status_code == 200 and "incorrect" in r.text.lower())

    r = anon.post("/client/login", data={"email": "portail@example.com", "password": known_password}, follow_redirects=False)
    record("POST /client/login réussi", r.status_code == 303 and "client_token" in r.cookies, f"status={r.status_code}")

    r = anon.get("/client/portal")
    record("GET /client/portal authentifié", r.status_code == 200 and "Client Portail Test" in r.text, f"status={r.status_code}")

    r = client.post(f"/client/{client_id}/portal/disable", follow_redirects=False)
    record("POST /client/{id}/portal/disable (admin)", r.status_code == 303)

    r = anon.get("/client/portal", follow_redirects=False)
    record("GET /client/portal après désactivation -> redirect login", r.status_code == 303 and r.headers.get("location") == "/client/login")


def test_client_portal_requires_auth() -> None:
    c = TestClient(app)
    r = c.get("/client/portal", follow_redirects=False)
    record("GET /client/portal sans auth -> redirect", r.status_code == 303 and r.headers.get("location") == "/client/login")


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
    test_upload_zip_unauthenticated()
    test_upload_zip_anonymous_allowed_when_opted_in()
    test_downloads_after_upload()
    test_intervention_detail()
    test_v10_pages()
    test_create_quote()
    test_comptabilite_requires_admin()
    test_comptabilite_page()
    test_export_comptable_xlsx()
    test_planning_requires_auth()
    test_planning_crud()
    test_relances_page()
    test_reminders_flow()
    test_client_portal_requires_auth()
    test_client_portal_flow()
    test_delete_requires_admin()
    test_invalid_login()

    passed = sum(1 for _, ok, _ in results if ok)
    failed = sum(1 for _, ok, _ in results if not ok)
    print(f"\n=== Résultat: {passed} PASS, {failed} FAIL / {len(results)} tests ===")
    try:
        if TEST_DB.exists():
            TEST_DB.unlink()
    except PermissionError:
        print(f"(info) base test non supprimée: {TEST_DB}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())

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
        "tax": "10",
        "description": "Test devis",
        "status": "draft",
    }, follow_redirects=False)
    record("POST /quotes", r.status_code == 303)


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

"""Tests unitaires pytest (migration progressive — complète run_tests.py)."""
from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]


def test_to_money_rounds_half_up():
    from app.helpers import to_money

    assert to_money("12.345") == Decimal("12.35")
    assert to_money(None) == Decimal("0.00")
    assert to_money(10) == Decimal("10.00")


def test_smtp_config_defaults():
    from app.services.mail import smtp_config

    cfg = smtp_config()
    assert "host" in cfg
    assert "port" in cfg
    assert isinstance(cfg["enabled"], bool)


def test_default_billing_amount_without_labor():
    from app.services.billing_defaults import default_billing_amount

    assert default_billing_amount(None) == 60.0


def test_health_endpoint():
    """Smoke test HTTP via TestClient (ne remplace pas la suite intégration)."""
    import os
    import sys

    sys.path.insert(0, str(BACKEND))
    os.chdir(BACKEND)
    db = BACKEND / "pytest_smoke.db"
    if db.exists():
        db.unlink()
    os.environ["DATABASE_URL"] = f"sqlite:///{db.as_posix()}"
    os.environ["SECRET_KEY"] = "pytest-secret"
    os.environ["ADMIN_PASSWORD"] = "testadmin2026"
    os.environ.pop("UPLOAD_API_KEY", None)

    from fastapi.testclient import TestClient

    from app.auth import create_default_admin
    from app.database import SessionLocal, init_db
    from app.main import app

    init_db()
    with SessionLocal() as session:
        create_default_admin(session)

    client = TestClient(app)
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body.get("status") == "ok"
    assert "version" in body

    if db.exists():
        db.unlink()

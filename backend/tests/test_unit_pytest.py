"""Tests unitaires pytest (migration progressive — complète run_tests.py)."""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

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


def test_parse_form_local_to_utc_paris_winter():
    """14:00 Europe/Paris (UTC+1 hiver) → 13:00 UTC."""
    from app.timeutil import parse_form_local_to_utc

    dt = parse_form_local_to_utc("2026-01-15T14:00")
    assert dt.tzinfo == timezone.utc
    assert dt.hour == 13
    assert dt.day == 15


def test_parse_form_local_to_utc_paris_summer():
    """14:00 Europe/Paris (UTC+2 été) → 12:00 UTC."""
    from app.timeutil import parse_form_local_to_utc

    dt = parse_form_local_to_utc("2026-07-15T14:00")
    assert dt.astimezone(timezone.utc).hour == 12


def test_format_app_local_roundtrip():
    from app.timeutil import format_app_local, parse_form_local_to_utc

    utc = parse_form_local_to_utc("2026-03-10T09:30")
    assert "09:30" in format_app_local(utc)


def test_reminder_succeeded_helpers():
    from app.appointment_reminders import _reminder_permanently_unusable, _reminder_succeeded

    assert _reminder_succeeded("sent", None) is True
    assert _reminder_succeeded("error", "sent") is True
    assert _reminder_succeeded("error", "sms_fail:x") is False
    assert _reminder_permanently_unusable("missing_client_email", "sms_not_configured") is True
    assert _reminder_permanently_unusable("smtp_error", "sms_not_configured") is False


def test_health_and_ready_endpoints(migrated_db):
    from fastapi.testclient import TestClient

    from app.auth import create_default_admin
    from app.database import SessionLocal
    from app.main import app

    with SessionLocal() as session:
        create_default_admin(session)

    client = TestClient(app)
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json().get("status") == "ok"
    assert "version" in r.json()

    ready = client.get("/ready")
    assert ready.status_code == 200
    assert ready.json().get("status") == "ready"


def test_migration_0011_columns_present(migrated_db, db_session):
    """Après upgrade head, appointment a reminder_opt_in + sms_reminder_sent_at."""
    from sqlalchemy import inspect

    from app.database import engine
    from app.models import Appointment

    insp = inspect(engine)
    cols = {c["name"] for c in insp.get_columns("appointment")}
    assert "reminder_opt_in" in cols
    assert "sms_reminder_sent_at" in cols

    row = Appointment(
        title="Test rappel",
        start_at=datetime(2026, 8, 1, 10, 0, tzinfo=timezone.utc),
        reminder_opt_in=True,
    )
    db_session.add(row)
    db_session.commit()
    db_session.refresh(row)
    assert row.reminder_opt_in is True
    assert row.sms_reminder_sent_at is None

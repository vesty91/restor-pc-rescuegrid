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


def test_local_date_crosses_midnight_paris():
    """23:30 UTC hiver = 00:30 Paris le lendemain — groupement planning."""
    from app.timeutil import local_date

    utc = datetime(2026, 1, 15, 23, 30, tzinfo=timezone.utc)
    assert local_date(utc) == datetime(2026, 1, 16).date()
    assert local_date(None) is None


def test_local_week_bounds_utc_monday_aligned():
    from app.timeutil import app_tz, local_week_bounds_utc

    start, end = local_week_bounds_utc(offset_weeks=0)
    assert start.tzinfo == timezone.utc
    assert (end - start).days == 7
    local_start = start.astimezone(app_tz())
    assert local_start.weekday() == 0
    assert local_start.hour == 0 and local_start.minute == 0


def test_sqlite_db_path_respects_database_url(tmp_path, monkeypatch):
    import sqlite3

    from app import backup as backup_module

    custom = tmp_path / "custom_atelier.db"
    conn = sqlite3.connect(custom)
    try:
        conn.execute("CREATE TABLE t (id INTEGER)")
        conn.commit()
    finally:
        conn.close()

    monkeypatch.setattr(backup_module, "DATABASE_URL", f"sqlite:///{custom.as_posix()}")
    assert backup_module._sqlite_db_path(tmp_path) == custom.resolve()

    monkeypatch.setattr(backup_module, "DATABASE_URL", "sqlite:///:memory:")
    assert backup_module._sqlite_db_path(tmp_path) is None


def test_reminder_succeeded_helpers():
    from app.appointment_reminders import _reminder_permanently_unusable, _reminder_succeeded

    assert _reminder_succeeded("sent", None) is True
    assert _reminder_succeeded("error", "sent") is True
    assert _reminder_succeeded("error", "sms_fail:x") is False
    assert _reminder_permanently_unusable("missing_client_email", "sms_not_configured") is True
    assert _reminder_permanently_unusable("smtp_error", "sms_not_configured") is False


def test_get_client_ip_ignores_xff_from_untrusted_peer(monkeypatch):
    from types import SimpleNamespace

    monkeypatch.delenv("TRUSTED_PROXY_CIDRS", raising=False)
    from app import deps

    deps.reload_trusted_proxy_networks()

    req = SimpleNamespace(
        client=SimpleNamespace(host="203.0.113.50"),
        headers={"x-forwarded-for": "1.2.3.4"},
    )
    assert deps.get_client_ip(req) == "203.0.113.50"


def test_get_client_ip_trusts_xff_from_localhost(monkeypatch):
    from types import SimpleNamespace

    monkeypatch.delenv("TRUSTED_PROXY_CIDRS", raising=False)
    from app import deps

    deps.reload_trusted_proxy_networks()

    req = SimpleNamespace(
        client=SimpleNamespace(host="127.0.0.1"),
        headers={"x-forwarded-for": "203.0.113.9, 127.0.0.1"},
    )
    assert deps.get_client_ip(req) == "203.0.113.9"


def test_get_client_ip_rejects_garbage_xff(monkeypatch):
    from types import SimpleNamespace

    monkeypatch.delenv("TRUSTED_PROXY_CIDRS", raising=False)
    from app import deps

    deps.reload_trusted_proxy_networks()

    req = SimpleNamespace(
        client=SimpleNamespace(host="127.0.0.1"),
        headers={"x-forwarded-for": "not-an-ip, also-bad"},
    )
    assert deps.get_client_ip(req) == "127.0.0.1"


def test_get_client_ip_custom_cidr_env(monkeypatch):
    from types import SimpleNamespace

    monkeypatch.setenv("TRUSTED_PROXY_CIDRS", "10.0.0.1/32")
    from app import deps

    deps.reload_trusted_proxy_networks()

    req = SimpleNamespace(
        client=SimpleNamespace(host="10.0.0.1"),
        headers={"x-real-ip": "198.51.100.7"},
    )
    assert deps.get_client_ip(req) == "198.51.100.7"

    # Peer hors liste → ignore XFF
    req2 = SimpleNamespace(
        client=SimpleNamespace(host="10.0.0.2"),
        headers={"x-forwarded-for": "198.51.100.7"},
    )
    assert deps.get_client_ip(req2) == "10.0.0.2"


def test_process_logo_image_png_roundtrip():
    from io import BytesIO

    from PIL import Image

    from app.logo_upload import process_logo_image

    buf = BytesIO()
    Image.new("RGB", (64, 32), color=(20, 80, 160)).save(buf, format="PNG")
    out = process_logo_image(buf.getvalue())
    assert out.startswith(b"\x89PNG\r\n\x1a\n")
    again = Image.open(BytesIO(out))
    assert again.size == (64, 32)


def test_process_logo_image_rejects_garbage():
    from app.logo_upload import process_logo_image

    try:
        process_logo_image(b"not-an-image")
        assert False, "devait lever ValueError"
    except ValueError:
        pass


def test_process_logo_image_resizes_large():
    from io import BytesIO

    from PIL import Image

    from app.logo_upload import process_logo_image

    buf = BytesIO()
    Image.new("RGB", (2000, 1000), color=(0, 0, 0)).save(buf, format="JPEG", quality=90)
    out = process_logo_image(buf.getvalue(), max_edge=1024)
    img = Image.open(BytesIO(out))
    assert max(img.size) <= 1024


def test_adapter_ram_wmi_cap_hidden(migrated_db):
    """AdapterRAM uint32 saturé (~4 Go) ne doit pas s'afficher comme VRAM réelle."""
    from app.main import _adapter_ram_bytes, _hardware_from_inventory, _pick_primary_gpu

    assert _adapter_ram_bytes(4_294_967_295) is None
    assert _adapter_ram_bytes(-1) is None
    assert _adapter_ram_bytes(12 * 1024**3) == 12 * 1024**3

    inv = {
        "video_controllers": [
            {"Name": "Microsoft Basic Display Adapter", "AdapterRAM": 0},
            {"Name": "NVIDIA GeForce RTX 4070 SUPER", "AdapterRAM": 4_294_967_295},
        ]
    }
    gpu = _pick_primary_gpu(inv)
    assert "4070" in gpu["Name"]
    specs = _hardware_from_inventory(inv)
    assert "4070" in specs["gpu"]
    assert specs["gpu_sub"] == ""  # pas de faux « 4 Go »

    inv2 = {
        "video_controllers": [
            {"Name": "NVIDIA GeForce RTX 4070 SUPER", "AdapterRAM": 12 * 1024**3},
        ]
    }
    assert _hardware_from_inventory(inv2)["gpu_sub"] == "12 Go"

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
    body = ready.json()
    assert body.get("status") == "ready"
    assert body.get("alembic")
    assert body.get("version")


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

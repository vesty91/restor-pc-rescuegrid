"""Compatibilité : ancien routes_v10 — délègue aux modules routes/ + services/."""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter
from fastapi.templating import Jinja2Templates

from .routes import intervention_extras as r_intervention_extras
from .routes import quotes as r_quotes
from .routes import relances as r_relances
from .routes import settings_admin as r_settings_admin
from .services.mail import _smtp_config, send_document_email, smtp_config
from .services.reminders import send_invoice_reminder, send_quote_reminder

__all__ = [
    "init_v10_routes",
    "send_document_email",
    "send_quote_reminder",
    "send_invoice_reminder",
    "_smtp_config",
    "smtp_config",
]


def init_v10_routes(
    templates: Jinja2Templates,
    storage_dir: Path,
    report_dir: Path,
    sanitize_filename,
    intervention_dir_fn,
    resolve_storage_path,
) -> APIRouter:
    """Assemble les routers issus du découpage de l'ancien monolith routes_v10."""
    # report_dir / resolve_storage_path conservés pour signature compatible main.py
    _ = (report_dir, resolve_storage_path)
    parent = APIRouter()
    parent.include_router(r_quotes.init_router(templates))
    parent.include_router(r_relances.init_router(templates))
    parent.include_router(r_settings_admin.init_router(templates))
    parent.include_router(
        r_intervention_extras.init_router(
            templates, storage_dir, sanitize_filename, intervention_dir_fn
        )
    )
    return parent

"""Montants / descriptions / échéances par défaut pour devis et factures."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from ..models import Intervention


def default_service_description(intervention: Intervention | None) -> str:
    if not intervention:
        return "Diagnostic atelier, contrôle système et rapport Restor-PC."
    score = f" Score santé {intervention.health_score}/100." if intervention.health_score is not None else ""
    return (
        "Diagnostic atelier, contrôle SMART, analyse Windows et rapport d'intervention Restor-PC."
        + score
    )


def default_billing_amount(intervention: Intervention | None) -> float:
    """Taux atelier Restor-PC : 60 €/h (ou forfait 60 € si pas de main-d'œuvre)."""
    if not intervention:
        return 60.0
    minutes = int(getattr(intervention, "labor_minutes", 0) or 0)
    rate = float(getattr(intervention, "labor_rate", 0) or 60.0)
    if minutes > 0:
        return round((minutes / 60.0) * rate, 2)
    return 60.0


def default_due_date(days: int = 30) -> str:
    return (datetime.now(timezone.utc) + timedelta(days=days)).strftime("%Y-%m-%d")

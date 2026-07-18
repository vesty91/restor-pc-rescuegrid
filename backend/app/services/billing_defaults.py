"""Montants / descriptions / échéances par défaut pour devis et factures."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from ..models import Intervention

# Modèles prêts à l'emploi (atelier Restor-PC).
SERVICE_TEMPLATES: list[dict[str, str | float]] = [
    {
        "id": "diagnostic",
        "label": "Diagnostic atelier (60 €)",
        "description": "Diagnostic atelier, contrôle SMART, analyse Windows et rapport d'intervention Restor-PC.",
        "amount": 60.0,
    },
    {
        "id": "nettoyage",
        "label": "Nettoyage / optimisation (80 €)",
        "description": "Nettoyage système, suppression logiciels indésirables, optimisation démarrage et contrôle santé disque.",
        "amount": 80.0,
    },
    {
        "id": "reinstall",
        "label": "Réinstallation Windows (120 €)",
        "description": "Sauvegarde données essentielles (si possible), réinstallation Windows, drivers de base et remise en service.",
        "amount": 120.0,
    },
    {
        "id": "recup",
        "label": "Récupération données (forfait 150 €)",
        "description": "Tentative de récupération de données utilisateur, export sur support externe et rapport des fichiers récupérés.",
        "amount": 150.0,
    },
]


def default_service_description(intervention: Intervention | None) -> str:
    if not intervention:
        return str(SERVICE_TEMPLATES[0]["description"])
    score = f" Score santé {intervention.health_score}/100." if intervention.health_score is not None else ""
    return str(SERVICE_TEMPLATES[0]["description"]) + score


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


def template_by_id(template_id: str) -> dict[str, str | float] | None:
    for item in SERVICE_TEMPLATES:
        if item["id"] == template_id:
            return item
    return None

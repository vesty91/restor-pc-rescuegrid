"""Utilitaires fuseau horaire atelier (Europe/Paris par défaut)."""
from __future__ import annotations

import os
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

APP_TIMEZONE_NAME = os.getenv("APP_TIMEZONE", "Europe/Paris").strip() or "Europe/Paris"


def app_tz() -> ZoneInfo:
    return ZoneInfo(APP_TIMEZONE_NAME)


def parse_form_local_to_utc(value: str, *, fmt: str = "%Y-%m-%dT%H:%M") -> datetime:
    """Interprète une saisie `datetime-local` comme heure atelier, stocke en UTC."""
    naive = datetime.strptime(value.strip(), fmt)
    # fold=0 : en transition DST ambiguë, préférer l'heure avant le changement.
    return naive.replace(tzinfo=app_tz(), fold=0).astimezone(timezone.utc)


def ensure_utc(dt: datetime) -> datetime:
    """Normalise un datetime (naïf = déjà UTC stocké) vers aware UTC."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def local_date(dt: datetime | None) -> date | None:
    """Jour civil atelier pour un instant UTC (évite le décalage de groupement)."""
    if dt is None:
        return None
    return ensure_utc(dt).astimezone(app_tz()).date()


def local_week_bounds_utc(*, offset_weeks: int = 0) -> tuple[datetime, datetime]:
    """
    Bornes [lundi 00:00, lundi+7) en heure atelier, converties en UTC pour SQL.
    offset_weeks=0 → semaine courante ; 1 → semaine suivante.
    """
    local_now = datetime.now(app_tz())
    monday = (local_now - timedelta(days=local_now.weekday())).replace(
        hour=0, minute=0, second=0, microsecond=0, fold=0
    ) + timedelta(weeks=offset_weeks)
    end = monday + timedelta(days=7)
    return monday.astimezone(timezone.utc), end.astimezone(timezone.utc)


def format_app_local(dt: datetime | None, *, with_time: bool = True) -> str:
    """Affiche un instant UTC en heure atelier."""
    if dt is None:
        return "—"
    local = ensure_utc(dt).astimezone(app_tz())
    if with_time:
        return local.strftime("%d/%m/%Y à %H:%M")
    return local.strftime("%d/%m/%Y")


def format_app_local_time(dt: datetime | None) -> str:
    if dt is None:
        return ""
    return ensure_utc(dt).astimezone(app_tz()).strftime("%H:%M")

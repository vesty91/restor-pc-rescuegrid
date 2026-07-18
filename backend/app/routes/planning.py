"""
routes/planning.py — Restor-PC RescueGrid
--------------------------------------------
Planning / rendez-vous atelier.

  GET  /planning                     → agenda (liste groupée par jour)
  POST /planning                     → créer un RDV
  POST /planning/{id}/status         → changer le statut
  POST /delete/appointment/{id}      → supprimer (admin)
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from itertools import groupby

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_session
from ..deps import get_user_or_redirect
from ..auth import get_admin_or_redirect
from ..helpers import paginate_query
from ..models import Appointment, Client, Intervention, User

router = APIRouter()
_templates: Jinja2Templates | None = None


def init_router(templates: Jinja2Templates) -> APIRouter:
    global _templates
    _templates = templates
    return router


APPOINTMENT_STATUSES = ["scheduled", "confirmed", "done", "cancelled", "no_show"]


@router.get("/planning", response_class=HTMLResponse)
def planning_list(request: Request, range_filter: str = "week", page: int = 1, session: Session = Depends(get_session)):
    user, redirect = get_user_or_redirect(request, session)
    if redirect:
        return redirect

    now = datetime.now(timezone.utc)
    query = select(Appointment).order_by(Appointment.start_at.asc())
    if range_filter == "week":
        start_week = (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
        end_week = start_week + timedelta(days=7)
        query = query.where(Appointment.start_at >= start_week, Appointment.start_at < end_week)
    elif range_filter == "next_week":
        start_week = (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=7)
        end_week = start_week + timedelta(days=7)
        query = query.where(Appointment.start_at >= start_week, Appointment.start_at < end_week)
    elif range_filter == "upcoming":
        query = query.where(Appointment.start_at >= now)
    # "all" : pas de filtre de date

    appointments, page, total_pages, total_items = paginate_query(session, query, page)
    # Clé "entries" (pas "items") : Jinja résout d'abord les attributs Python avant
    # les clés de dict, et dict.items est une méthode intégrée — "day_group.items"
    # renverrait donc la méthode plutôt que la liste si on l'avait nommée ainsi.
    grouped = [
        {"day": day, "entries": list(entries)}
        for day, entries in groupby(appointments, key=lambda a: a.start_at.date())
    ]

    clients = session.scalars(select(Client).order_by(Client.name)).all()
    interventions = session.scalars(select(Intervention).order_by(Intervention.created_at.desc())).all()
    technicians = session.scalars(select(User).where(User.is_active).order_by(User.username)).all()

    return _templates.TemplateResponse("planning.html", {
        "request": request,
        "user": user,
        "active_page": "planning",
        "grouped": grouped,
        "clients": clients,
        "interventions": interventions,
        "technicians": technicians,
        "range_filter": range_filter,
        "appointment_statuses": APPOINTMENT_STATUSES,
        "page": page,
        "total_pages": total_pages,
        "total_items": total_items,
    })


@router.post("/planning")
def create_appointment(
    request: Request,
    title: str = Form(...),
    client_id: int = Form(0),
    intervention_id: int = Form(0),
    technician_id: int = Form(0),
    start_at: str = Form(...),
    end_at: str = Form(""),
    notes: str = Form(""),
    session: Session = Depends(get_session),
):
    user, redirect = get_user_or_redirect(request, session)
    if redirect:
        return redirect
    try:
        start_dt = datetime.strptime(start_at, "%Y-%m-%dT%H:%M").replace(tzinfo=timezone.utc)
    except ValueError:
        raise HTTPException(status_code=400, detail="Date/heure de début invalide")
    end_dt = None
    if end_at:
        try:
            end_dt = datetime.strptime(end_at, "%Y-%m-%dT%H:%M").replace(tzinfo=timezone.utc)
        except ValueError:
            end_dt = None
    appointment = Appointment(
        title=title.strip(),
        client_id=client_id or None,
        intervention_id=intervention_id or None,
        technician_id=technician_id or None,
        start_at=start_dt,
        end_at=end_dt,
        notes=notes.strip() or None,
    )
    session.add(appointment)
    session.commit()
    return RedirectResponse("/planning", status_code=303)


@router.post("/planning/{appointment_id}/status")
def update_appointment_status(
    appointment_id: int,
    request: Request,
    status: str = Form(...),
    session: Session = Depends(get_session),
):
    user, redirect = get_user_or_redirect(request, session)
    if redirect:
        return redirect
    appointment = session.scalars(select(Appointment).where(Appointment.id == appointment_id)).first()
    if not appointment:
        raise HTTPException(status_code=404, detail="Rendez-vous introuvable")
    if status in APPOINTMENT_STATUSES:
        appointment.status = status
        session.commit()
    return RedirectResponse("/planning", status_code=303)


@router.post("/delete/appointment/{appointment_id}")
def delete_appointment(appointment_id: int, request: Request, session: Session = Depends(get_session)):
    user, redirect = get_admin_or_redirect(request, session)
    if redirect:
        return redirect
    appointment = session.scalars(select(Appointment).where(Appointment.id == appointment_id)).first()
    if appointment:
        session.delete(appointment)
        session.commit()
    return RedirectResponse("/planning", status_code=303)

"""
routes/planning.py — Restor-PC RescueGrid
--------------------------------------------
Planning / rendez-vous atelier.

  GET  /planning                     → agenda (liste groupée par jour)
  POST /planning                     → créer un RDV
  POST /planning/{id}/status         → changer le statut
  POST /planning/{id}/resend-email   → renvoyer l'email RDV
  POST /planning/{id}/resend-sms     → renvoyer le SMS / WhatsApp RDV
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

import logging

from ..database import get_session
from ..deps import get_user_or_redirect
from ..auth import get_admin_or_redirect, log_activity
from ..helpers import paginate_query, status_label_fr
from ..models import Appointment, Client, Intervention, User
from ..services.mail import send_text_email
from ..services.sms import send_sms, send_whatsapp, sms_configured, whatsapp_configured
from ..timeutil import format_app_local, format_app_local_time, local_date, local_week_bounds_utc, parse_form_local_to_utc

logger = logging.getLogger(__name__)

router = APIRouter()
_templates: Jinja2Templates | None = None


def init_router(templates: Jinja2Templates) -> APIRouter:
    global _templates
    _templates = templates
    return router


APPOINTMENT_STATUSES = ["scheduled", "confirmed", "done", "cancelled", "no_show"]


def _notify_client_appointment(session: Session, appointment: Appointment, *, event: str) -> str | None:
    """Envoie un email au client lié au RDV. Retourne un code détail ou None si pas d'envoi."""
    if not appointment.client_id:
        return "no_client"
    client = session.get(Client, appointment.client_id)
    if not client or not client.email:
        return "missing_client_email"
    start_local = format_app_local(appointment.start_at)
    end_txt = ""
    if appointment.end_at:
        end_txt = f" (fin prévue {format_app_local_time(appointment.end_at)})"
    status_fr = status_label_fr(appointment.status)
    if event == "created":
        subject = f"Confirmation de rendez-vous — {appointment.title}"
        intro = "Votre rendez-vous a été planifié chez Restor-PC."
    elif event == "cancelled":
        subject = f"Annulation de rendez-vous — {appointment.title}"
        intro = "Votre rendez-vous chez Restor-PC a été annulé."
    elif event == "resend":
        subject = f"Rappel de rendez-vous — {appointment.title}"
        intro = "Voici un rappel de votre rendez-vous chez Restor-PC."
    elif event == "reminder":
        subject = f"Rappel J-1 — {appointment.title}"
        intro = "Rappel : votre rendez-vous chez Restor-PC a lieu demain."
    else:
        subject = f"Mise à jour de rendez-vous — {appointment.title}"
        intro = f"Le statut de votre rendez-vous est passé à : {status_fr}."
    notes = f"\nNotes : {appointment.notes}\n" if appointment.notes else ""
    body = (
        f"Bonjour {client.contact_name or client.name},\n\n"
        f"{intro}\n\n"
        f"Titre : {appointment.title}\n"
        f"Date : {start_local}{end_txt}\n"
        f"Statut : {status_fr}\n"
        f"{notes}\n"
        f"Espace client : https://espace-client.restor-pc.fr/client/login\n\n"
        f"Cordialement,\nRestor-PC\n"
    )
    ok, detail = send_text_email(to_email=client.email, subject=subject, body=body)
    if ok:
        logger.info("Email RDV %s envoyé à %s (%s)", appointment.id, client.email, event)
        return "sent"
    logger.warning("Email RDV %s vers %s échoué: %s", appointment.id, client.email, detail)
    return detail


def _appointment_sms_body(client: Client, appointment: Appointment, *, event: str) -> str:
    start_local = format_app_local(appointment.start_at).replace(" à ", " ")
    status_fr = status_label_fr(appointment.status)
    if event == "created":
        return (
            f"Restor-PC: RDV confirme le {start_local} — {appointment.title}. "
            f"Espace client: espace-client.restor-pc.fr"
        )
    if event == "cancelled":
        return f"Restor-PC: RDV annule ({appointment.title}) prevu le {start_local}."
    if event == "resend":
        return f"Restor-PC: rappel RDV le {start_local} — {appointment.title}."
    if event == "reminder":
        return f"Restor-PC: rappel J-1 — RDV demain {start_local} — {appointment.title}."
    return f"Restor-PC: RDV mis a jour ({status_fr}) le {start_local} — {appointment.title}."


def _notify_client_appointment_sms(session: Session, appointment: Appointment, *, event: str) -> str | None:
    """SMS et/ou WhatsApp. Retourne un code détail ou None si pas d'envoi demandé côté config."""
    if not appointment.client_id:
        return "no_client"
    client = session.get(Client, appointment.client_id)
    if not client or not (client.phone or "").strip():
        return "missing_client_phone"
    body = _appointment_sms_body(client, appointment, event=event)
    details: list[str] = []
    if sms_configured():
        ok, detail = send_sms(client.phone, body)
        details.append(f"sms:{detail}" if ok else f"sms_fail:{detail}")
    if whatsapp_configured():
        ok, detail = send_whatsapp(client.phone, body)
        details.append(f"wa:{detail}" if ok else f"wa_fail:{detail}")
    if not details:
        return "sms_not_configured"
    joined = ",".join(details)
    if any(x.endswith(":sent") for x in details):
        logger.info("SMS/WA RDV %s vers %s (%s) %s", appointment.id, client.phone, event, joined)
        return "sent"
    logger.warning("SMS/WA RDV %s echoue: %s", appointment.id, joined)
    return joined


@router.get("/planning", response_class=HTMLResponse)
def planning_list(request: Request, range_filter: str = "week", page: int = 1, session: Session = Depends(get_session)):
    user, redirect = get_user_or_redirect(request, session)
    if redirect:
        return redirect

    now = datetime.now(timezone.utc)
    query = select(Appointment).order_by(Appointment.start_at.asc())
    if range_filter == "week":
        start_week, end_week = local_week_bounds_utc(offset_weeks=0)
        query = query.where(Appointment.start_at >= start_week, Appointment.start_at < end_week)
    elif range_filter == "next_week":
        start_week, end_week = local_week_bounds_utc(offset_weeks=1)
        query = query.where(Appointment.start_at >= start_week, Appointment.start_at < end_week)
    elif range_filter == "upcoming":
        query = query.where(Appointment.start_at >= now)
    # "all" : pas de filtre de date

    appointments, page, total_pages, total_items = paginate_query(session, query, page)
    # Clé "entries" (pas "items") : Jinja résout d'abord les attributs Python avant
    # les clés de dict, et dict.items est une méthode intégrée — "day_group.items"
    # renverrait donc la méthode plutôt que la liste si on l'avait nommée ainsi.
    # Groupement par jour CIVIL atelier (Europe/Paris), pas par date UTC.
    grouped = [
        {"day": day, "entries": list(entries)}
        for day, entries in groupby(appointments, key=lambda a: local_date(a.start_at))
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
        "sms_configured": sms_configured() or whatsapp_configured(),
        "page": page,
        "total_pages": total_pages,
        "total_items": total_items,
    })


def _truthy_form(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on", "o", "oui"}


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
    notify_email: str = Form("on"),
    notify_sms: str = Form(""),
    reminder_opt_in: str = Form("on"),
    session: Session = Depends(get_session),
):
    user, redirect = get_user_or_redirect(request, session)
    if redirect:
        return redirect
    try:
        start_dt = parse_form_local_to_utc(start_at)
    except ValueError:
        raise HTTPException(status_code=400, detail="Date/heure de début invalide")
    end_dt = None
    if end_at:
        try:
            end_dt = parse_form_local_to_utc(end_at)
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
        reminder_opt_in=_truthy_form(reminder_opt_in),
    )
    session.add(appointment)
    session.commit()
    session.refresh(appointment)
    mail_detail = None
    sms_detail = None
    if _truthy_form(notify_email):
        mail_detail = _notify_client_appointment(session, appointment, event="created")
    if _truthy_form(notify_sms):
        sms_detail = _notify_client_appointment_sms(session, appointment, event="created")
    log_activity(
        session, user, "appointment.create",
        f"{appointment.id} mail={mail_detail or 'skipped'} sms={sms_detail or 'skipped'}",
    )
    session.commit()
    parts = []
    if mail_detail:
        parts.append(f"mail={mail_detail}")
    if sms_detail:
        parts.append(f"sms={sms_detail}")
    q = ("?" + "&".join(parts)) if parts else ""
    return RedirectResponse(f"/planning{q}", status_code=303)


@router.post("/planning/{appointment_id}/resend-email")
def resend_appointment_email(
    appointment_id: int,
    request: Request,
    session: Session = Depends(get_session),
):
    user, redirect = get_user_or_redirect(request, session)
    if redirect:
        return redirect
    appointment = session.scalars(select(Appointment).where(Appointment.id == appointment_id)).first()
    if not appointment:
        raise HTTPException(status_code=404, detail="Rendez-vous introuvable")
    mail_detail = _notify_client_appointment(session, appointment, event="resend")
    log_activity(session, user, "appointment.resend_email", f"{appointment.id} mail={mail_detail}")
    session.commit()
    return RedirectResponse(f"/planning?mail={mail_detail}&range_filter=upcoming", status_code=303)


@router.post("/planning/{appointment_id}/resend-sms")
def resend_appointment_sms(
    appointment_id: int,
    request: Request,
    session: Session = Depends(get_session),
):
    user, redirect = get_user_or_redirect(request, session)
    if redirect:
        return redirect
    appointment = session.scalars(select(Appointment).where(Appointment.id == appointment_id)).first()
    if not appointment:
        raise HTTPException(status_code=404, detail="Rendez-vous introuvable")
    sms_detail = _notify_client_appointment_sms(session, appointment, event="resend")
    log_activity(session, user, "appointment.resend_sms", f"{appointment.id} sms={sms_detail}")
    session.commit()
    return RedirectResponse(f"/planning?sms={sms_detail}&range_filter=upcoming", status_code=303)


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
    mail_detail = None
    sms_detail = None
    if status in APPOINTMENT_STATUSES and status != appointment.status:
        appointment.status = status
        session.commit()
        event = "cancelled" if status == "cancelled" else "updated"
        mail_detail = _notify_client_appointment(session, appointment, event=event)
        if sms_configured() or whatsapp_configured():
            sms_detail = _notify_client_appointment_sms(session, appointment, event=event)
        log_activity(
            session, user, "appointment.status",
            f"{appointment.id} {status} mail={mail_detail} sms={sms_detail}",
        )
        session.commit()
    parts = []
    if mail_detail:
        parts.append(f"mail={mail_detail}")
    if sms_detail:
        parts.append(f"sms={sms_detail}")
    q = ("?" + "&".join(parts)) if parts else ""
    return RedirectResponse(f"/planning{q}", status_code=303)


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

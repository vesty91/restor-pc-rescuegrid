"""
routes/machines.py — Restor-PC RescueGrid
-------------------------------------------
Toutes les routes liées aux machines.

  GET  /machines               → liste des machines (page dédiée)
  GET  /machine/{id}           → fiche machine
  POST /machines               → créer une machine
  POST /delete/machine/{id}    → supprimer une machine
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_session
from ..deps import get_user_or_redirect
from ..auth import get_admin_or_redirect
from ..helpers import paginate_query
from ..models import Intervention, Machine

router = APIRouter()
_templates: Jinja2Templates | None = None
_hardware_for_intervention = None  # injecté depuis main.py


def init_router(templates: Jinja2Templates, hardware_fn) -> APIRouter:
    global _templates, _hardware_for_intervention
    _templates = templates
    _hardware_for_intervention = hardware_fn
    return router


# ── Pages ────────────────────────────────────────────────────────────────────

@router.get("/machines", response_class=HTMLResponse)
def machines_list(request: Request, page: int = 1, session: Session = Depends(get_session)):
    user, redirect = get_user_or_redirect(request, session)
    if redirect:
        return redirect
    query = select(Machine).order_by(Machine.last_intervention.desc().nulls_last())
    machines, page, total_pages, total_items = paginate_query(session, query, page)
    return _templates.TemplateResponse("machines.html", {
        "request": request,
        "user": user,
        "active_page": "machines",
        "machines": machines,
        "page": page,
        "total_pages": total_pages,
        "total_items": total_items,
    })


@router.get("/machine/{machine_id}", response_class=HTMLResponse)
def machine_detail(machine_id: int, request: Request, session: Session = Depends(get_session)):
    user, redirect = get_user_or_redirect(request, session)
    if redirect:
        return redirect
    machine = session.scalars(select(Machine).where(Machine.id == machine_id)).first()
    if not machine:
        raise HTTPException(status_code=404, detail="Machine introuvable")
    interventions = session.scalars(
        select(Intervention)
        .where(Intervention.machine_id == machine_id)
        .order_by(Intervention.created_at.desc())
    ).all()
    latest = interventions[0] if interventions else None
    hardware = _hardware_for_intervention(latest)
    best_score = max(
        (i.health_score for i in interventions if i.health_score is not None),
        default=None,
    )
    return _templates.TemplateResponse("machine_detail.html", {
        "request": request,
        "user": user,
        "active_page": "machines",
        "machine": machine,
        "interventions": interventions,
        "hardware": hardware,
        "best_score": best_score,
    })


# ── Actions ───────────────────────────────────────────────────────────────────

@router.post("/machines")
def create_machine(
    request: Request,
    bios_serial: str = Form(""),
    machine_name: str = Form(""),
    manufacturer: str = Form(""),
    model: str = Form(""),
    session: Session = Depends(get_session),
):
    user, redirect = get_user_or_redirect(request, session)
    if redirect:
        return redirect
    machine = Machine(
        bios_serial=bios_serial.strip() or None,
        machine_name=machine_name.strip() or None,
        manufacturer=manufacturer.strip() or None,
        model=model.strip() or None,
    )
    session.add(machine)
    session.commit()
    return RedirectResponse("/machines", status_code=303)


@router.post("/delete/machine/{machine_id}")
def delete_machine(machine_id: int, request: Request, session: Session = Depends(get_session)):
    user, redirect = get_admin_or_redirect(request, session)
    if redirect:
        return redirect
    machine = session.scalars(select(Machine).where(Machine.id == machine_id)).first()
    if machine:
        session.delete(machine)
        session.commit()
    return RedirectResponse("/machines", status_code=303)

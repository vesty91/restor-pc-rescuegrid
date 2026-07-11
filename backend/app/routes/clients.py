"""
routes/clients.py — Restor-PC RescueGrid
------------------------------------------
Toutes les routes liées aux clients.

  GET  /clients                → liste des clients (page dédiée)
  GET  /client/{id}            → fiche client
  POST /clients                → créer un client
  POST /client/{id}/update     → modifier un client
  POST /delete/client/{id}     → supprimer un client
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
from ..models import Client, Intervention

router = APIRouter()
_templates: Jinja2Templates | None = None


def init_router(templates: Jinja2Templates) -> APIRouter:
    global _templates
    _templates = templates
    return router


# ── Pages ────────────────────────────────────────────────────────────────────

@router.get("/clients", response_class=HTMLResponse)
def clients_list(request: Request, page: int = 1, session: Session = Depends(get_session)):
    user, redirect = get_user_or_redirect(request, session)
    if redirect:
        return redirect
    query = select(Client).order_by(Client.created_at.desc())
    clients, page, total_pages, total_items = paginate_query(session, query, page)
    return _templates.TemplateResponse("clients.html", {
        "request": request,
        "user": user,
        "active_page": "clients",
        "clients": clients,
        "page": page,
        "total_pages": total_pages,
        "total_items": total_items,
    })


@router.get("/client/{client_id}", response_class=HTMLResponse)
def client_detail(client_id: int, request: Request, session: Session = Depends(get_session)):
    user, redirect = get_user_or_redirect(request, session)
    if redirect:
        return redirect
    client = session.scalars(select(Client).where(Client.id == client_id)).first()
    if not client:
        raise HTTPException(status_code=404, detail="Client introuvable")
    interventions = session.scalars(
        select(Intervention)
        .where(Intervention.client_id == client_id)
        .order_by(Intervention.created_at.desc())
    ).all()
    return _templates.TemplateResponse("client_detail.html", {
        "request": request,
        "user": user,
        "active_page": "clients",
        "client": client,
        "interventions": interventions,
    })


# ── Actions ───────────────────────────────────────────────────────────────────

@router.post("/clients")
def create_client(
    request: Request,
    name: str = Form(...),
    email: str = Form(""),
    phone: str = Form(""),
    address: str = Form(""),
    contact_name: str = Form(""),
    session: Session = Depends(get_session),
):
    user, redirect = get_user_or_redirect(request, session)
    if redirect:
        return redirect
    client = Client(
        name=name.strip(),
        email=email.strip() or None,
        phone=phone.strip() or None,
        address=address.strip() or None,
        contact_name=contact_name.strip() or None,
    )
    session.add(client)
    session.commit()
    return RedirectResponse("/clients", status_code=303)


@router.post("/client/{client_id}/update")
def update_client(
    client_id: int,
    request: Request,
    name: str = Form(...),
    email: str = Form(""),
    phone: str = Form(""),
    address: str = Form(""),
    contact_name: str = Form(""),
    session: Session = Depends(get_session),
):
    user, redirect = get_user_or_redirect(request, session)
    if redirect:
        return redirect
    client = session.scalars(select(Client).where(Client.id == client_id)).first()
    if not client:
        raise HTTPException(status_code=404, detail="Client introuvable")
    client.name = name.strip()
    client.email = email.strip() or None
    client.phone = phone.strip() or None
    client.address = address.strip() or None
    client.contact_name = contact_name.strip() or None
    session.commit()
    return RedirectResponse(f"/client/{client_id}", status_code=303)


@router.post("/delete/client/{client_id}")
def delete_client(client_id: int, request: Request, session: Session = Depends(get_session)):
    user, redirect = get_admin_or_redirect(request, session)
    if redirect:
        return redirect
    client = session.scalars(select(Client).where(Client.id == client_id)).first()
    if client:
        session.delete(client)
        session.commit()
    return RedirectResponse("/clients", status_code=303)

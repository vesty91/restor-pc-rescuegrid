"""
routes/tickets.py — Restor-PC RescueGrid
  GET  /tickets
  POST /tickets
  POST /delete/ticket/{id}
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_session
from ..deps import get_user_or_redirect
from ..auth import get_admin_or_redirect
from ..helpers import paginate_query
from ..models import Intervention, Ticket

router = APIRouter()
_templates: Jinja2Templates | None = None


def init_router(templates: Jinja2Templates) -> APIRouter:
    global _templates
    _templates = templates
    return router


@router.get("/tickets", response_class=HTMLResponse)
def tickets_list(request: Request, page: int = 1, session: Session = Depends(get_session)):
    user, redirect = get_user_or_redirect(request, session)
    if redirect:
        return redirect
    query = select(Ticket).order_by(Ticket.created_at.desc())
    tickets, page, total_pages, total_items = paginate_query(session, query, page)
    interventions = session.scalars(select(Intervention).order_by(Intervention.created_at.desc())).all()
    return _templates.TemplateResponse("tickets.html", {
        "request": request,
        "user": user,
        "active_page": "tickets",
        "tickets": tickets,
        "interventions": interventions,
        "page": page,
        "total_pages": total_pages,
        "total_items": total_items,
    })


@router.post("/tickets")
def create_ticket(
    request: Request,
    intervention_id: int = Form(...),
    title: str = Form(...),
    description: str = Form(""),
    priority: str = Form("medium"),
    status: str = Form("open"),
    session: Session = Depends(get_session),
):
    user, redirect = get_user_or_redirect(request, session)
    if redirect:
        return redirect
    intervention = session.get(Intervention, intervention_id)
    ticket = Ticket(
        intervention_id=intervention_id,
        client_id=intervention.client_id if intervention else None,
        title=title.strip(),
        description=description.strip() or None,
        priority=priority,
        status=status,
    )
    session.add(ticket)
    session.commit()
    return RedirectResponse("/tickets", status_code=303)


@router.post("/delete/ticket/{ticket_id}")
def delete_ticket(ticket_id: int, request: Request, session: Session = Depends(get_session)):
    user, redirect = get_admin_or_redirect(request, session)
    if redirect:
        return redirect
    ticket = session.scalars(select(Ticket).where(Ticket.id == ticket_id)).first()
    if ticket:
        session.delete(ticket)
        session.commit()
    return RedirectResponse("/tickets", status_code=303)

"""
routes/parts.py — Restor-PC RescueGrid
-----------------------------------------
  GET  /parts          → inventaire
  POST /parts          → ajouter une pièce
  POST /delete/part/{id} → supprimer
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
from ..models import Part

router = APIRouter()
_templates: Jinja2Templates | None = None


def init_router(templates: Jinja2Templates) -> APIRouter:
    global _templates
    _templates = templates
    return router


@router.get("/parts", response_class=HTMLResponse)
def parts_list(request: Request, page: int = 1, session: Session = Depends(get_session)):
    user, redirect = get_user_or_redirect(request, session)
    if redirect:
        return redirect
    query = select(Part).order_by(Part.part_type, Part.brand)
    parts, page, total_pages, total_items = paginate_query(session, query, page)
    return _templates.TemplateResponse("parts.html", {
        "request": request,
        "user": user,
        "active_page": "parts",
        "parts": parts,
        "page": page,
        "total_pages": total_pages,
        "total_items": total_items,
    })


@router.post("/parts")
def create_part(
    request: Request,
    part_type: str = Form(...),
    brand: str = Form(""),
    model: str = Form(""),
    serial_number: str = Form(""),
    capacity_gb: str = Form(""),
    quantity: int = Form(1),
    notes: str = Form(""),
    session: Session = Depends(get_session),
):
    user, redirect = get_user_or_redirect(request, session)
    if redirect:
        return redirect
    part = Part(
        part_type=part_type.strip(),
        brand=brand.strip() or None,
        model=model.strip() or None,
        serial_number=serial_number.strip() or None,
        capacity_gb=int(capacity_gb) if capacity_gb.strip().isdigit() else None,
        quantity=max(1, quantity),
        notes=notes.strip() or None,
    )
    session.add(part)
    session.commit()
    return RedirectResponse("/parts", status_code=303)


@router.post("/delete/part/{part_id}")
def delete_part(part_id: int, request: Request, session: Session = Depends(get_session)):
    user, redirect = get_admin_or_redirect(request, session)
    if redirect:
        return redirect
    part = session.scalars(select(Part).where(Part.id == part_id)).first()
    if part:
        session.delete(part)
        session.commit()
    return RedirectResponse("/parts", status_code=303)

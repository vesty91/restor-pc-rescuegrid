"""Détail intervention, photos, signature, main-d'œuvre, pièces, export CSV."""
from __future__ import annotations

import base64
import csv
import io
import os
import re
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth import get_user_or_redirect, log_activity
from ..database import get_session
from ..helpers import generate_ai_summary, to_money
from ..models import Intervention, InterventionPart, InterventionPhoto, Invoice, Part, Quote, Ticket
from ..services.billing_defaults import default_billing_amount, default_due_date

router = APIRouter()
_templates: Jinja2Templates | None = None
_storage_dir: Path | None = None
_sanitize_filename = None
_intervention_dir_fn = None

MAX_PHOTO_BYTES = int(os.getenv("MAX_PHOTO_BYTES", str(8 * 1024 * 1024)))
MAX_SIGNATURE_BYTES = int(os.getenv("MAX_SIGNATURE_BYTES", str(2 * 1024 * 1024)))


def init_router(templates: Jinja2Templates, storage_dir: Path, sanitize_filename, intervention_dir_fn) -> APIRouter:
    global _templates, _storage_dir, _sanitize_filename, _intervention_dir_fn
    _templates = templates
    _storage_dir = storage_dir
    _sanitize_filename = sanitize_filename
    _intervention_dir_fn = intervention_dir_fn
    (storage_dir / "photos").mkdir(parents=True, exist_ok=True)
    (storage_dir / "signatures").mkdir(parents=True, exist_ok=True)
    return router


@router.get("/intervention/{intervention_id}", response_class=HTMLResponse)
def intervention_detail(intervention_id: int, request: Request, session: Session = Depends(get_session)):
    user, redirect = get_user_or_redirect(request, session)
    if redirect:
        return redirect
    intervention = session.scalars(select(Intervention).where(Intervention.id == intervention_id)).first()
    if not intervention:
        raise HTTPException(status_code=404, detail="Intervention introuvable")
    parts = session.scalars(select(Part).order_by(Part.part_type)).all()
    tickets = session.scalars(select(Ticket).where(Ticket.intervention_id == intervention_id)).all()
    quotes = session.scalars(
        select(Quote).where(Quote.intervention_id == intervention_id).order_by(Quote.created_at.desc())
    ).all()
    invoices = session.scalars(
        select(Invoice).where(Invoice.intervention_id == intervention_id).order_by(Invoice.created_at.desc())
    ).all()
    folder = _intervention_dir_fn(intervention)
    if folder and not intervention.ai_summary:
        intervention.ai_summary = generate_ai_summary(intervention, folder)
        session.commit()
    return _templates.TemplateResponse("intervention_detail.html", {
        "active_page": "interventions",
        "request": request,
        "intervention": intervention,
        "parts": parts,
        "tickets": tickets,
        "quotes": quotes,
        "invoices": invoices,
        "user": user,
        "atelier_statuses": ["nouvelle", "en_attente", "en_cours", "termine", "livre", "facture"],
        "default_amount": default_billing_amount(intervention),
        "default_quote_until": default_due_date(30),
        "default_invoice_due": default_due_date(0),
    })


@router.post("/intervention/{intervention_id}/photo")
async def upload_intervention_photo(
    intervention_id: int,
    request: Request,
    phase: str = Form("during"),
    file: UploadFile = File(...),
    session: Session = Depends(get_session),
):
    user, redirect = get_user_or_redirect(request, session)
    if redirect:
        return redirect
    intervention = session.scalars(select(Intervention).where(Intervention.id == intervention_id)).first()
    if not intervention:
        raise HTTPException(status_code=404, detail="Intervention introuvable")
    if phase not in {"before", "during", "after"}:
        phase = "during"
    if not file.content_type or not file.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="Image requise")
    content = await file.read(MAX_PHOTO_BYTES + 1)
    if len(content) > MAX_PHOTO_BYTES:
        raise HTTPException(status_code=413, detail="Image trop volumineuse")
    safe = _sanitize_filename(file.filename or "photo.jpg")
    rel = f"photos/int_{intervention_id}_{phase}_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}_{safe}"
    target = _storage_dir / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(content)
    session.add(InterventionPhoto(intervention_id=intervention_id, phase=phase, file_path=rel))
    log_activity(session, user, "intervention.photo", f"#{intervention_id} {phase}")
    session.commit()
    return RedirectResponse(f"/intervention/{intervention_id}", status_code=303)


@router.post("/intervention/{intervention_id}/signature")
async def save_intervention_signature(
    intervention_id: int,
    request: Request,
    signature_data: str = Form(...),
    session: Session = Depends(get_session),
):
    user, redirect = get_user_or_redirect(request, session)
    if redirect:
        return redirect
    intervention = session.scalars(select(Intervention).where(Intervention.id == intervention_id)).first()
    if not intervention:
        raise HTTPException(status_code=404, detail="Intervention introuvable")
    match = re.match(r"data:image/(png|jpeg|jpg);base64,(.+)", signature_data, re.I)
    if not match:
        raise HTTPException(status_code=400, detail="Signature invalide")
    ext = "png" if match.group(1).lower() == "png" else "jpg"
    try:
        raw = base64.b64decode(match.group(2), validate=True)
    except Exception:
        raise HTTPException(status_code=400, detail="Signature invalide (encodage base64 incorrect)")
    if len(raw) > MAX_SIGNATURE_BYTES:
        raise HTTPException(status_code=413, detail="Signature trop volumineuse")
    rel = f"signatures/int_{intervention_id}_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}.{ext}"
    target = _storage_dir / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(raw)
    intervention.signature_path = rel
    log_activity(session, user, "intervention.signature", f"#{intervention_id}")
    session.commit()
    return RedirectResponse(f"/intervention/{intervention_id}", status_code=303)


@router.post("/intervention/{intervention_id}/labor")
def update_intervention_labor(
    intervention_id: int,
    request: Request,
    labor_minutes: int = Form(0),
    labor_rate: float = Form(60.0),
    session: Session = Depends(get_session),
):
    user, redirect = get_user_or_redirect(request, session)
    if redirect:
        return redirect
    intervention = session.scalars(select(Intervention).where(Intervention.id == intervention_id)).first()
    if not intervention:
        raise HTTPException(status_code=404, detail="Intervention introuvable")
    intervention.labor_minutes = max(labor_minutes, 0)
    intervention.labor_rate = to_money(labor_rate if labor_rate > 0 else 60.0)
    log_activity(session, user, "intervention.labor", f"#{intervention_id} {labor_minutes}min")
    session.commit()
    return RedirectResponse(f"/intervention/{intervention_id}", status_code=303)


@router.post("/intervention/{intervention_id}/parts")
def add_intervention_part(
    intervention_id: int,
    request: Request,
    part_id: int = Form(...),
    quantity: int = Form(1),
    notes: str = Form(""),
    session: Session = Depends(get_session),
):
    user, redirect = get_user_or_redirect(request, session)
    if redirect:
        return redirect
    intervention = session.scalars(select(Intervention).where(Intervention.id == intervention_id)).first()
    part = session.scalars(select(Part).where(Part.id == part_id)).first()
    if not intervention or not part:
        raise HTTPException(status_code=404, detail="Intervention ou pièce introuvable")
    qty = max(quantity, 1)
    if part.quantity < qty:
        raise HTTPException(status_code=400, detail="Stock insuffisant")
    part.quantity -= qty
    session.add(InterventionPart(
        intervention_id=intervention_id, part_id=part_id, quantity=qty, notes=notes or None,
    ))
    log_activity(session, user, "intervention.part", f"#{intervention_id} part#{part_id} x{qty}")
    session.commit()
    return RedirectResponse(f"/intervention/{intervention_id}", status_code=303)


@router.get("/export/interventions.csv")
def export_interventions_csv(request: Request, session: Session = Depends(get_session)):
    user, redirect = get_user_or_redirect(request, session)
    if redirect:
        return redirect
    interventions = session.scalars(select(Intervention).order_by(Intervention.created_at.desc())).all()
    stream = io.StringIO()
    writer = csv.writer(stream)
    writer.writerow(["ID", "Date", "Client", "Machine", "Score", "Disque", "Statut"])
    for item in interventions:
        writer.writerow([
            item.id,
            item.created_at.strftime("%Y-%m-%d %H:%M"),
            item.client.name if item.client else "",
            item.machine_name or "",
            item.health_score or "",
            item.disk_risk or "",
            item.status,
        ])
    return StreamingResponse(
        iter([stream.getvalue().encode("utf-8-sig")]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=interventions.csv"},
    )

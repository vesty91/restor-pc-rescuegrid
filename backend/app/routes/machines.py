"""
routes/machines.py — Restor-PC RescueGrid
-------------------------------------------
Toutes les routes liées aux machines.

  GET  /machines               → liste des machines (page dédiée)
  GET  /machine/{id}           → fiche machine
  GET  /machine/{id}/label     → bon de dépôt imprimable + QR
  GET  /d/{id}                 → lien court QR (auth → fiche, sinon porte)
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


# ── Bon de dépôt / QR ─────────────────────────────────────────────────────────

def _absolute_url(request: Request, path: str) -> str:
    base = str(request.base_url).rstrip("/")
    if not path.startswith("/"):
        path = "/" + path
    return base + path


@router.get("/machine/{machine_id}/label", response_class=HTMLResponse)
def machine_deposit_label(machine_id: int, request: Request, session: Session = Depends(get_session)):
    """Bon de dépôt imprimable avec QR → /d/{id}."""
    import html as html_mod

    from ..helpers import qr_png_data_uri

    user, redirect = get_user_or_redirect(request, session)
    if redirect:
        return redirect
    machine = session.scalars(select(Machine).where(Machine.id == machine_id)).first()
    if not machine:
        raise HTTPException(status_code=404, detail="Machine introuvable")

    latest = session.scalars(
        select(Intervention)
        .where(Intervention.machine_id == machine_id)
        .order_by(Intervention.created_at.desc())
    ).first()
    client_name = "—"
    if latest and latest.client:
        client_name = latest.client.name or "—"

    scan_url = _absolute_url(request, f"/d/{machine.id}")
    qr_uri = qr_png_data_uri(scan_url)
    name = html_mod.escape(machine.machine_name or f"Machine #{machine.id}")
    manufacturer = html_mod.escape(machine.manufacturer or "—")
    model = html_mod.escape(machine.model or "—")
    bios = html_mod.escape(machine.bios_serial or "—")
    client_esc = html_mod.escape(client_name)
    deposited = machine.created_at.strftime("%d/%m/%Y %H:%M") if machine.created_at else "—"

    label_html = f"""<!doctype html><html lang="fr"><head><meta charset="utf-8"><title>Bon de dépôt</title>
<style>
body{{font-family:Segoe UI,Arial,sans-serif;margin:20px;color:#111}}
.label{{width:105mm;border:2px solid #111;border-radius:8px;padding:14px;display:grid;grid-template-columns:1fr 28mm;gap:10px;align-items:start}}
h1{{font-size:15px;margin:0 0 6px;color:#0a84ff}} .id{{font-size:22px;font-weight:800;margin-bottom:8px}}
p{{margin:3px 0;font-size:12px}} .qr{{width:26mm;height:26mm}} .hint{{font-size:10px;color:#555;margin-top:6px}}
@media print{{button{{display:none}} body{{margin:0}}}}
</style></head><body>
<button onclick="print()">Imprimer</button>
<div class="label">
  <div>
    <h1>Restor-PC — Bon de dépôt</h1>
    <div class="id">MAC-{machine.id:06d}</div>
    <p><strong>Client :</strong> {client_esc}</p>
    <p><strong>Machine :</strong> {name}</p>
    <p><strong>Marque / modèle :</strong> {manufacturer} / {model}</p>
    <p><strong>BIOS :</strong> {bios}</p>
    <p><strong>Dépôt :</strong> {deposited}</p>
    <p class="hint">Scan QR → fiche machine atelier</p>
  </div>
  <img class="qr" src="{qr_uri}" alt="QR">
</div>
</body></html>"""
    return HTMLResponse(label_html)


@router.get("/d/{machine_id}", response_class=HTMLResponse)
def machine_deposit_scan(machine_id: int, request: Request, session: Session = Depends(get_session)):
    """Lien court scannable : auth → fiche machine, sinon page porte + login?next=."""
    from ..auth import get_current_user

    machine = session.scalars(select(Machine).where(Machine.id == machine_id)).first()
    if not machine:
        raise HTTPException(status_code=404, detail="Machine introuvable")

    user = get_current_user(request, session)
    if user:
        return RedirectResponse(f"/machine/{machine_id}", status_code=303)

    next_path = f"/machine/{machine_id}"
    label = machine.machine_name or f"Machine #{machine.id}"
    return _templates.TemplateResponse(
        "deposit_gate.html",
        {
            "request": request,
            "machine": machine,
            "machine_label": label,
            "login_url": f"/login?next={next_path}",
        },
    )

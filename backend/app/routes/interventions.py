"""
routes/interventions.py — Restor-PC RescueGrid v12.3
------------------------------------------------------
Routes interventions NON dupliquées avec routes_v10.py

routes_v10.py gère déjà :
  GET  /intervention/{id}              → on retire d'ici
  POST /intervention/{id}/photo        → on retire d'ici
  POST /intervention/{id}/signature    → on retire d'ici
  POST /intervention/{id}/labor        → on retire d'ici
  POST /intervention/{id}/parts        → on retire d'ici

Ce module gère uniquement :
  GET  /interventions                  → liste (nouvelle page)
  POST /interventions                  → créer manuellement
  POST /upload                         → import ZIP agent
  POST /intervention/{id}/status      → changer statut
  POST /delete/intervention/{id}      → supprimer
  GET  /intervention/{id}/label       → étiquette
  GET  /intervention/{id}/download/*  → téléchargements
  GET  /export/interventions.xlsx     → export Excel
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from io import BytesIO

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from openpyxl import Workbook
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_session
from ..deps import get_user_or_redirect
from ..auth import get_admin_or_redirect
from ..helpers import apply_intervention_filters, generate_ai_summary
from ..models import Client, Intervention, Machine, Part, Quote, Invoice

logger = logging.getLogger(__name__)

router = APIRouter()
_templates: Jinja2Templates | None = None
_STORAGE_DIR: Path | None = None
_REPORT_DIR: Path | None = None
_UPLOAD_DIR: Path | None = None
_sanitize_filename = None
_intervention_dir = None
_resolve_storage_path = None
_safe_extract_zip = None
_hardware_for_intervention = None
_default_billing_amount = None
MAX_UPLOAD_BYTES = 2 * 1024 * 1024 * 1024


def init_router(templates, storage_dir, report_dir, upload_dir,
                sanitize_fn, intervention_dir_fn, resolve_storage_fn,
                safe_extract_fn, hardware_fn, billing_fn) -> APIRouter:
    global _templates, _STORAGE_DIR, _REPORT_DIR, _UPLOAD_DIR
    global _sanitize_filename, _intervention_dir, _resolve_storage_path
    global _safe_extract_zip, _hardware_for_intervention, _default_billing_amount
    _templates = templates
    _STORAGE_DIR = storage_dir
    _REPORT_DIR = report_dir
    _UPLOAD_DIR = upload_dir
    _sanitize_filename = sanitize_fn
    _intervention_dir = intervention_dir_fn
    _resolve_storage_path = resolve_storage_fn
    _safe_extract_zip = safe_extract_fn
    _hardware_for_intervention = hardware_fn
    _default_billing_amount = billing_fn
    return router


# ── Page liste interventions ─────────────────────────────────────────────────

@router.get("/interventions", response_class=HTMLResponse)
def interventions_list(
    request: Request,
    status: str = "",
    sort: str = "",
    q: str = "",
    session: Session = Depends(get_session),
):
    user, redirect = get_user_or_redirect(request, session)
    if redirect:
        return redirect

    if q:
        query = f"%{q}%"
        interventions = session.scalars(
            select(Intervention).where(
                (Intervention.title.ilike(query))
                | (Intervention.machine_name.ilike(query))
                | (Intervention.bios_serial.ilike(query))
            ).order_by(Intervention.created_at.desc())
        ).all()
    else:
        iq = apply_intervention_filters(select(Intervention), status or None, sort or None)
        interventions = session.scalars(iq).all()

    clients = session.scalars(select(Client).order_by(Client.name)).all()
    machines = session.scalars(select(Machine).order_by(Machine.machine_name)).all()

    return _templates.TemplateResponse("interventions.html", {
        "request": request,
        "user": user,
        "active_page": "interventions",
        "interventions": interventions,
        "clients": clients,
        "machines": machines,
        "filter_status": status,
        "filter_sort": sort,
        "search_query": q,
        "atelier_statuses": ["nouvelle", "en_attente", "en_cours", "termine", "livre", "facture"],
    })


# ── Créer manuellement ────────────────────────────────────────────────────────

@router.post("/interventions")
def create_intervention(
    request: Request,
    title: str = Form(...),
    client_id: int = Form(...),
    machine_id: int = Form(0),
    machine_name: str = Form(""),
    status: str = Form("nouvelle"),
    session: Session = Depends(get_session),
):
    user, redirect = get_user_or_redirect(request, session)
    if redirect:
        return redirect
    intervention = Intervention(
        client_id=client_id,
        machine_id=machine_id if machine_id > 0 else None,
        title=title.strip(),
        machine_name=machine_name.strip() or None,
        status=status,
    )
    session.add(intervention)
    session.commit()
    return RedirectResponse("/interventions", status_code=303)


# ── Import ZIP agent ──────────────────────────────────────────────────────────

@router.post("/upload")
async def upload_intervention(
    request: Request,
    client_name: str = Form(...),
    file: UploadFile = File(...),
    upload_key: str = Form(""),
    session: Session = Depends(get_session),
):
    from ..auth import verify_upload_access
    if not verify_upload_access(request, session, upload_key or None):
        raise HTTPException(status_code=401, detail="Authentification requise pour l'import ZIP")
    if not file.filename or not file.filename.lower().endswith(".zip"):
        raise HTTPException(status_code=400, detail="Archive ZIP requise")

    safe_name = _sanitize_filename(client_name)
    safe_file = _sanitize_filename(Path(file.filename).name)
    archive_path = _UPLOAD_DIR / f"{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_{safe_name}_{safe_file}"

    content = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="Fichier trop volumineux")
    archive_path.write_bytes(content)

    import json
    dest_dir = _REPORT_DIR / archive_path.stem
    dest_dir.mkdir(parents=True, exist_ok=True)
    _safe_extract_zip(archive_path, dest_dir)

    manifest_path = dest_dir / "manifest.json"
    metadata: dict = {}
    if manifest_path.exists():
        try:
            metadata = json.loads(manifest_path.read_text(encoding="utf-8-sig", errors="replace"))
        except Exception as exc:
            logger.warning("Lecture manifest impossible: %s", exc)

    bios_serial = metadata.get("bios_serial") or metadata.get("SerialNumber") or ""
    machine_name_raw = metadata.get("machine_name") or metadata.get("ComputerName") or safe_name
    health_score = metadata.get("health_score")
    disk_risk = metadata.get("disk_risk") or metadata.get("DiskRisk")
    data_loss_risk = metadata.get("data_loss_risk") or metadata.get("DataLossRisk")

    client = session.scalars(select(Client).where(Client.name == client_name.strip())).first()
    if not client:
        client = Client(name=client_name.strip())
        session.add(client)
        session.flush()

    machine = None
    if bios_serial:
        machine = session.scalars(select(Machine).where(Machine.bios_serial == bios_serial)).first()
    if not machine:
        machine = Machine(bios_serial=bios_serial or None, machine_name=machine_name_raw)
        session.add(machine)
        session.flush()
    else:
        machine.last_intervention = datetime.now(timezone.utc)

    report_path_rel = None
    for name in ["rapport.html", "report.html", "RescueGrid_Report.html"]:
        p = dest_dir / name
        if p.exists():
            report_path_rel = str(p.relative_to(_STORAGE_DIR))
            break

    intervention = Intervention(
        client_id=client.id,
        machine_id=machine.id,
        title=f"Intervention {machine_name_raw} — {datetime.now(timezone.utc).strftime('%d/%m/%Y')}",
        machine_name=machine_name_raw,
        bios_serial=bios_serial or None,
        health_score=int(health_score) if health_score is not None else None,
        disk_risk=str(disk_risk) if disk_risk else None,
        data_loss_risk=str(data_loss_risk) if data_loss_risk else None,
        archive_path=str(archive_path.relative_to(_STORAGE_DIR)),
        report_path=report_path_rel,
        status="nouvelle",
    )
    session.add(intervention)
    session.flush()  # obtenir intervention.id avant generate_ai_summary
    folder = dest_dir if dest_dir.exists() else None
    intervention.ai_summary = generate_ai_summary(intervention, folder)
    session.commit()
    return RedirectResponse(f"/intervention/{intervention.id}", status_code=303)


# ── Changer statut ────────────────────────────────────────────────────────────

@router.post("/intervention/{intervention_id}/status")
def update_status(
    intervention_id: int,
    request: Request,
    status: str = Form(...),
    session: Session = Depends(get_session),
):
    user, redirect = get_user_or_redirect(request, session)
    if redirect:
        return redirect
    intervention = session.scalars(select(Intervention).where(Intervention.id == intervention_id)).first()
    if not intervention:
        raise HTTPException(status_code=404, detail="Intervention introuvable")
    allowed = {"nouvelle", "en_attente", "en_cours", "termine", "livre", "facture"}
    intervention.status = status if status in allowed else "nouvelle"
    session.commit()
    return RedirectResponse(f"/intervention/{intervention_id}", status_code=303)


# ── Supprimer ─────────────────────────────────────────────────────────────────

@router.post("/delete/intervention/{intervention_id}")
def delete_intervention(intervention_id: int, request: Request, session: Session = Depends(get_session)):
    user, redirect = get_admin_or_redirect(request, session)
    if redirect:
        return redirect
    intervention = session.scalars(select(Intervention).where(Intervention.id == intervention_id)).first()
    if intervention:
        session.delete(intervention)
        session.commit()
    return RedirectResponse("/interventions", status_code=303)


# ── Étiquette ─────────────────────────────────────────────────────────────────

@router.get("/intervention/{intervention_id}/label", response_class=HTMLResponse)
def intervention_label(intervention_id: int, request: Request, session: Session = Depends(get_session)):
    user, redirect = get_user_or_redirect(request, session)
    if redirect:
        return redirect
    intervention = session.scalars(select(Intervention).where(Intervention.id == intervention_id)).first()
    if not intervention:
        raise HTTPException(status_code=404, detail="Intervention introuvable")
    client = intervention.client
    machine = intervention.machine
    html = f"""<!doctype html><html lang="fr"><head><meta charset="utf-8"><title>Étiquette</title>
<style>body{{font-family:Segoe UI,Arial,sans-serif;margin:20px}}
.label{{width:95mm;border:2px solid #111;border-radius:8px;padding:12px}}
h1{{font-size:16px;margin:0 0 8px;color:#0a84ff}} .id{{font-size:22px;font-weight:800}}
p{{margin:4px 0;font-size:13px}} @media print{{button{{display:none}}}}</style>
</head><body><button onclick="print()">Imprimer</button><div class="label">
<h1>Restor-PC RescueGrid</h1><div class="id">INT-{intervention.id:06d}</div>
<p><strong>Client :</strong> {client.name if client else '—'}</p>
<p><strong>Machine :</strong> {intervention.machine_name or (machine.machine_name if machine else '—')}</p>
<p><strong>BIOS :</strong> {intervention.bios_serial or '—'}</p>
<p><strong>Statut :</strong> {intervention.status}</p>
<p><strong>Date :</strong> {intervention.created_at.strftime('%d/%m/%Y %H:%M')}</p>
</div></body></html>"""
    return HTMLResponse(html)


# ── Téléchargements ───────────────────────────────────────────────────────────

@router.get("/intervention/{intervention_id}/download/zip")
def download_zip(intervention_id: int, request: Request, session: Session = Depends(get_session)):
    user, redirect = get_user_or_redirect(request, session)
    if redirect:
        return redirect
    intervention = session.scalars(select(Intervention).where(Intervention.id == intervention_id)).first()
    if not intervention or not intervention.archive_path:
        raise HTTPException(status_code=404, detail="Archive introuvable")
    path = _resolve_storage_path(intervention.archive_path)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Fichier introuvable")
    return FileResponse(path, filename=path.name, media_type="application/zip")


@router.get("/intervention/{intervention_id}/download/report")
def download_report(intervention_id: int, request: Request, session: Session = Depends(get_session)):
    user, redirect = get_user_or_redirect(request, session)
    if redirect:
        return redirect
    intervention = session.scalars(select(Intervention).where(Intervention.id == intervention_id)).first()
    if not intervention or not intervention.report_path:
        raise HTTPException(status_code=404, detail="Rapport introuvable")
    path = _resolve_storage_path(intervention.report_path)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Fichier introuvable")
    return FileResponse(path, filename=path.name, media_type="text/html")


@router.get("/intervention/{intervention_id}/download/manifest")
def download_manifest(intervention_id: int, request: Request, session: Session = Depends(get_session)):
    user, redirect = get_user_or_redirect(request, session)
    if redirect:
        return redirect
    intervention = session.scalars(select(Intervention).where(Intervention.id == intervention_id)).first()
    if not intervention:
        raise HTTPException(status_code=404, detail="Intervention introuvable")
    folder = _intervention_dir(intervention)
    if not folder:
        raise HTTPException(status_code=404, detail="Dossier introuvable")
    # Noms réellement produits par l'agent Windows (voir evidence_manifest.json),
    # avec quelques alias conservés par compatibilité.
    for name in ["evidence_manifest.json", "hashes.sha256.txt", "manifest.sha256", "checksums.sha256"]:
        p = folder / name
        if p.exists():
            media_type = "application/json" if p.suffix == ".json" else "text/plain"
            return FileResponse(p, filename=p.name, media_type=media_type)
    raise HTTPException(status_code=404, detail="Manifest introuvable")


# ── Export Excel ──────────────────────────────────────────────────────────────

@router.get("/export/interventions.xlsx")
def export_xlsx(request: Request, session: Session = Depends(get_session)):
    user, redirect = get_user_or_redirect(request, session)
    if redirect:
        return redirect
    interventions = session.scalars(select(Intervention).order_by(Intervention.created_at.desc())).all()
    wb = Workbook()
    ws = wb.active
    ws.title = "Interventions"
    ws.append(["ID", "Date", "Client", "Machine", "Titre", "Score", "Disque", "Données", "Statut"])
    for i in interventions:
        ws.append([
            i.id,
            i.created_at.strftime("%d/%m/%Y %H:%M"),
            i.client.name if i.client else "",
            i.machine_name or "",
            i.title,
            i.health_score,
            i.disk_risk or "",
            i.data_loss_risk or "",
            i.status,
        ])
    buf = BytesIO()
    wb.save(buf)
    buf.seek(0)
    return StreamingResponse(buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=interventions.xlsx"})

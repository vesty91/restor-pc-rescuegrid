"""Utilitaires v10 : documents, analyse IA, filtres."""
from __future__ import annotations

import json
import base64
import html
import io
import logging
import subprocess
import tempfile
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path

from fastapi.responses import HTMLResponse, Response

from .models import Intervention, Invoice, Quote

logger = logging.getLogger(__name__)

_MONEY_QUANTUM = Decimal("0.01")


def to_money(value) -> Decimal:
    """Convertit une valeur formulaire/float en Decimal monétaire (2 décimales)."""
    if value is None:
        return Decimal("0.00")
    if isinstance(value, Decimal):
        return value.quantize(_MONEY_QUANTUM, rounding=ROUND_HALF_UP)
    try:
        return Decimal(str(value)).quantize(_MONEY_QUANTUM, rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError, TypeError):
        return Decimal("0.00")


def next_document_number(session, prefix: str, model, field_name: str) -> str:
    """Génère un numéro unique journalier (DEV-YYYYMMDD-0001 / INV-YYYYMMDD-0001)."""
    import re
    from datetime import datetime, timezone

    from sqlalchemy import select

    today = datetime.now(timezone.utc).strftime("%Y%m%d")
    pattern = f"{prefix}-{today}-%"
    field = getattr(model, field_name)
    existing = session.scalars(select(field).where(field.like(pattern))).all()
    max_index = 0
    for number in existing:
        match = re.match(rf"^{prefix}-{today}-(\d{{4,}})$", str(number or ""))
        if match:
            max_index = max(max_index, int(match.group(1)))
    return f"{prefix}-{today}-{max_index + 1:04d}"


def allocate_document_number(session, prefix: str, model, field_name: str, build_row, *, max_attempts: int = 8):
    """Alloue un numéro de document puis commit, avec retry sur collision UNIQUE."""
    from fastapi import HTTPException
    from sqlalchemy.exc import IntegrityError

    last_exc: Exception | None = None
    for _ in range(max_attempts):
        number = next_document_number(session, prefix, model, field_name)
        row = build_row(number)
        session.add(row)
        try:
            session.commit()
            return row
        except IntegrityError as exc:
            session.rollback()
            last_exc = exc
            continue
    raise HTTPException(
        status_code=409,
        detail=f"Impossible d'allouer un numéro {prefix} unique après {max_attempts} tentatives",
    ) from last_exc



def _company_info() -> dict:
    """Configuration société via variables d'environnement, avec valeurs Restor-PC auto-entrepreneur."""
    import os
    return {
        "name": os.getenv("RESTORPC_COMPANY_NAME", "RESTOR-PC"),
        "subtitle": os.getenv("RESTORPC_COMPANY_SUBTITLE", "Dépannage informatique - Diagnostic & récupération de données"),
        "address": os.getenv("RESTORPC_COMPANY_ADDRESS", "3 rue Auber\\n91330 Yerres"),
        "phone": os.getenv("RESTORPC_COMPANY_PHONE", "07 67 28 23 65"),
        "email": os.getenv("RESTORPC_COMPANY_EMAIL", "contact@restor-pc.fr"),
        "site": os.getenv("RESTORPC_COMPANY_SITE", "www.restor-pc.fr"),
        "siret": os.getenv("RESTORPC_COMPANY_SIRET", "SIRET : non renseigné"),
        "vat": os.getenv("RESTORPC_COMPANY_VAT", "TVA non applicable, article 293 B du CGI"),
        "payment_terms": os.getenv("RESTORPC_PAYMENT_TERMS", "Montant à régler à réception, en espèces ou par virement immédiat. Paiement par carte bancaire / TPE non disponible. RIB / IBAN : à compléter avant envoi si règlement par virement."),
        "legal": os.getenv("RESTORPC_LEGAL_TEXT", "TVA non applicable, article 293 B du Code Général des Impôts. Merci pour votre confiance."),
    }


def _logo_data_uri() -> str:
    """Logo Restor-PC embarqué dans les PDF/HTML pour impression hors-ligne."""
    logo_path = Path(__file__).resolve().parents[1] / "static" / "restorpc_logo.png"
    if not logo_path.exists():
        return ""
    try:
        data = base64.b64encode(logo_path.read_bytes()).decode("ascii")
        return f"data:image/png;base64,{data}"
    except Exception as exc:
        logger.warning("Impossible de charger une image integree PDF: %s", exc)
        return ""


def _signature_data_uri() -> str:
    """Signature Restor-PC séparée du logo.

    Pour l'activer, placer un fichier dans backend/static :
      - restorpc_signature.png
      - signature_restormpc.png
      - signature.png
    Si aucun fichier n'existe, le PDF affiche une zone de signature vide.
    """
    static_dir = Path(__file__).resolve().parents[1] / "static"
    for name in ("restorpc_signature.png", "signature_restormpc.png", "signature.png"):
        signature_path = static_dir / name
        if signature_path.exists():
            try:
                data = base64.b64encode(signature_path.read_bytes()).decode("ascii")
                return f"data:image/png;base64,{data}"
            except Exception as exc:
                logger.warning("Lecture signature client impossible: %s", exc)
                return ""
    return ""



def _client_signature_data_uri(intervention: Intervention | None) -> str:
    """Signature client enregistrée sur l'intervention, injectée dans devis/factures."""
    if not intervention or not getattr(intervention, "signature_path", None):
        return ""
    import os
    candidates = []
    raw = Path(str(intervention.signature_path))
    if raw.is_absolute():
        candidates.append(raw)
    storage_root = Path(os.getenv("STORAGE_PATH", str(Path(__file__).resolve().parents[1] / "storage"))).resolve()
    candidates.append(storage_root / str(intervention.signature_path))
    candidates.append(Path(__file__).resolve().parents[1] / "storage" / str(intervention.signature_path))
    for signature_path in candidates:
        try:
            if signature_path.exists() and signature_path.is_file():
                suffix = signature_path.suffix.lower().lstrip(".") or "png"
                mime = "jpeg" if suffix in {"jpg", "jpeg"} else "png"
                data = base64.b64encode(signature_path.read_bytes()).decode("ascii")
                return f"data:image/{mime};base64,{data}"
        except Exception as exc:
            logger.warning("Lecture signature client impossible (%s): %s", candidate, exc)
            continue
    return ""

def _clean_description(description: str | None, intervention: Intervention | None = None) -> str:
    """Évite d'afficher un nom de dossier technique dans les documents client."""
    raw = (description or "").strip()
    if not raw and intervention:
        raw = (intervention.title or "").strip()

    technical_patterns = [
        "Intervention_20",
        "_TEST_",
        "TEST_",
        "2026",
        "RescueGrid",
    ]
    looks_technical = len(raw) > 80 or any(token in raw for token in technical_patterns)
    if not raw or looks_technical:
        return "Diagnostic atelier, contrôle système, analyse SMART et rapport d'intervention Restor-PC."

    return raw


def _service_presentation(description: str) -> tuple[str, str, list[str]]:
    """Transforme une désignation technique en formulation plus claire pour le client."""
    raw = (description or "").strip()
    lower = raw.lower()

    title = "Diagnostic complet atelier avec contrôle système, stockage et rapport d’intervention"
    subtitle = (
        "Prestation forfaitaire comprenant la prise en charge de l’équipement en atelier, "
        "le contrôle du matériel et du système, l’analyse des anomalies constatées et la remise "
        "d’un rapport d’intervention Restor-PC."
    )
    bullets = [
        "Diagnostic matériel et logiciel de l’équipement confié.",
        "Vérification du système Windows, de la stabilité et des anomalies visibles.",
        "Contrôle du stockage et des indicateurs SMART lorsque disponibles.",
        "Compte-rendu clair des constats techniques et recommandations Restor-PC.",
    ]

    if any(k in lower for k in ["sauvegarde", "backup", "clone", "migration"]):
        title = "Sauvegarde / sécurisation des données avec contrôle du support de stockage"
        subtitle = (
            "Prestation de sauvegarde ou de sécurisation des données comprenant la vérification du support, "
            "la préparation de l’intervention et un compte-rendu des opérations réalisées."
        )
        bullets = [
            "Vérification du support source et du support de destination.",
            "Sauvegarde, copie ou préparation des données selon l’intervention.",
            "Contrôle de cohérence des fichiers ou de l’opération réalisée.",
            "Compte-rendu Restor-PC avec recommandations de sécurisation.",
        ]
    elif any(k in lower for k in ["forensic", "récup", "recup", "données", "donnees"]):
        title = "Diagnostic stockage / récupération de données avec rapport d’intervention"
        subtitle = (
            "Analyse orientée stockage et données comprenant l’évaluation du support, "
            "l’identification des risques et la restitution d’un rapport d’intervention compréhensible."
        )
        bullets = [
            "Analyse de l’état du support de stockage et des risques détectés.",
            "Contrôle SMART et vérification de la lisibilité des données lorsque possible.",
            "Identification des anomalies, erreurs ou signes de défaillance.",
            "Rapport d’intervention Restor-PC avec recommandations de récupération ou sauvegarde.",
        ]
    elif any(k in lower for k in ["smart", "disque", "ssd", "hdd", "nvme", "stockage"]):
        title = "Diagnostic stockage et santé disque avec rapport d’intervention"
        subtitle = (
            "Prestation de diagnostic orientée stockage comprenant le contrôle de la santé du disque, "
            "l’analyse des alertes SMART et la remise d’un rapport d’intervention Restor-PC."
        )
        bullets = [
            "Contrôle de l’état du support de stockage et des alertes SMART disponibles.",
            "Analyse des anomalies, secteurs défectueux ou signes d’usure détectés.",
            "Vérification de l’impact possible sur le fonctionnement du système.",
            "Rapport détaillé avec recommandations de sauvegarde, remplacement ou remise en service.",
        ]
    elif any(k in lower for k in ["windows", "boot", "démarrage", "demarrage", "système", "systeme"]):
        title = "Diagnostic système Windows et contrôle de stabilité avec rapport d’intervention"
        subtitle = (
            "Prestation de diagnostic système comprenant l’analyse du démarrage, du fonctionnement de Windows, "
            "des erreurs détectées et la remise d’un rapport d’intervention détaillé."
        )
        bullets = [
            "Contrôle du démarrage, du système Windows et des erreurs visibles.",
            "Vérification des anomalies pouvant impacter les performances ou la stabilité.",
            "Analyse des éléments techniques utiles au diagnostic atelier.",
            "Compte-rendu Restor-PC avec recommandations de réparation, optimisation ou sauvegarde.",
        ]

    return title, subtitle, bullets


def document_html(
    doc_type: str,
    number: str,
    client_name: str,
    created: str,
    due: str,
    description: str,
    amount: float,
    tax: float,
    total: float,
    status: str,
    extra: str = "",
    detail_title: str | None = None,
    detail_subtitle: str | None = None,
    detail_bullets: list[str] | None = None,
    client_signature_uri: str = "",
    client_email: str = "",
    client_phone: str = "",
    client_address: str = "",
    client_contact: str = "",
) -> str:
    import html
    company = _company_info()
    signature_uri = _signature_data_uri()
    title = "DEVIS" if doc_type == "quote" else "FACTURE"
    status_labels = {
        "draft": "Brouillon",
        "sent": "Envoyée",
        "issued": "Émise",
        "accepted": "Accepté",
        "paid": "Payée",
        "cancelled": "Annulée",
    }
    safe = lambda value: html.escape(str(value or ""))
    def br(value: str) -> str:
        return safe(value).replace("\\n", "<br>")
    label_status = status_labels.get((status or "").lower(), status or "-")
    due_label = "Validité jusqu'au" if doc_type == "quote" else "Échéance"
    total_label = "TOTAL DU DEVIS" if doc_type == "quote" else "TOTAL À PAYER"
    client_block_title = "ADRESSÉ À" if doc_type == "quote" else "FACTURÉ À"
    total = amount  # micro-entrepreneur : TVA non applicable
    detail_title = detail_title or description
    detail_subtitle = detail_subtitle or "Intervention forfaitaire incluant diagnostic, contrôle, actions réalisées et validation du bon fonctionnement."
    detail_bullets = detail_bullets or [
        "Diagnostic matériel et système.",
        "Contrôle disque, SMART et état Windows lorsque disponible.",
        "Analyse des journaux et recommandations de réparation.",
        "Remise d'un rapport d'intervention Restor-PC.",
    ]

    return f"""<!doctype html>
<html lang="fr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{safe(title)} {safe(number)} - RESTOR-PC</title>
<style>
  * {{ box-sizing:border-box; }}
  html, body {{ margin:0; padding:0; }}
  body {{
    font-family:Arial, Helvetica, sans-serif;
    color:#1f2937;
    background:#f1f5f9;
    -webkit-print-color-adjust:exact;
    print-color-adjust:exact;
  }}
  .toolbar {{
    padding:14px 20px;
    background:#0f172a;
    text-align:center;
  }}
  .print-btn {{
    border:0;
    border-radius:6px;
    background:#13a7bd;
    color:white;
    padding:10px 18px;
    font-weight:700;
    cursor:pointer;
  }}
  .page {{
    width:210mm;
    min-height:297mm;
    margin:0 auto;
    background:white;
    padding:12mm 14mm 9mm;
  }}
  table {{ border-collapse:collapse; }}
  .doc-header {{ width:100%; }}
  .doc-header td {{ vertical-align:top; }}
  .company-name {{
    margin:0 0 1mm;
    font-size:17px;
    font-weight:800;
    color:#0f172a;
  }}
  .company-subtitle {{
    margin:0 0 2mm;
    font-size:9.6px;
    color:#475569;
  }}
  .company-line {{
    margin:0.4mm 0;
    font-size:9.6px;
    line-height:1.35;
    color:#334155;
  }}
  .doc-meta {{ text-align:right; }}
  .doc-meta .doc-title {{
    margin:0 0 2mm;
    font-size:21px;
    font-weight:800;
    letter-spacing:.4px;
    text-transform:uppercase;
    color:#0f172a;
  }}
  .doc-meta p {{
    margin:0.5mm 0;
    font-size:9.8px;
    color:#334155;
  }}
  .badge {{
    display:inline-block;
    margin-top:1.5mm;
    padding:1.3mm 4mm;
    border-radius:999px;
    background:#d7f8e9;
    color:#047857;
    font-size:9.6px;
    font-weight:800;
  }}
  .accent-line {{
    height:2.4px;
    background:#13a7bd;
    border:0;
    margin:3mm 0 3.5mm;
  }}
  .info-card {{
    width:100%;
    background:#eef3f8;
    border-radius:8px;
    margin-bottom:3.5mm;
  }}
  .info-card td {{
    width:50%;
    vertical-align:top;
    padding:3mm 5mm;
  }}
  .info-card td + td {{ border-left:1px solid #d7e0ea; }}
  .info-card h3, .technical h3, .payment-box h3 {{
    margin:0 0 1.6mm;
    font-size:10.4px;
    font-weight:800;
    text-transform:uppercase;
    color:#0f172a;
  }}
  .info-card p {{
    margin:0;
    font-size:9.8px;
    line-height:1.4;
    color:#334155;
  }}
  .info-card strong {{ color:#0f172a; }}
  .technical {{ margin-bottom:3.5mm; }}
  .technical ul {{ margin:0; padding:0; list-style:none; }}
  .technical li {{
    position:relative;
    padding-left:5mm;
    margin:0.7mm 0;
    font-size:9.8px;
    line-height:1.32;
    color:#334155;
  }}
  .technical li:before {{
    content:"\\2713";
    position:absolute;
    left:0;
    color:#13a7bd;
    font-weight:900;
  }}
  table.items {{ width:100%; margin-bottom:3.5mm; }}
  table.items th {{
    background:#1f2733;
    color:white;
    font-size:9.2px;
    font-weight:700;
    text-transform:uppercase;
    letter-spacing:.2px;
    padding:2mm 2.6mm;
    text-align:left;
  }}
  table.items td {{
    padding:2mm 2.6mm;
    border-bottom:1px solid #e2e8f0;
    vertical-align:top;
    font-size:9.8px;
  }}
  .right {{ text-align:right; white-space:nowrap; }}
  .designation strong {{ display:block; margin-bottom:1mm; color:#0f172a; }}
  .designation small {{ color:#64748b; line-height:1.35; }}
  table.totals {{ width:78mm; margin:0 0 3.5mm auto; }}
  table.totals td {{
    padding:1.5mm 3mm;
    font-size:9.8px;
    border-bottom:1px solid #e2e8f0;
    color:#334155;
  }}
  table.totals td.value {{ text-align:right; font-weight:700; color:#0f172a; }}
  table.totals tr.grand td {{
    background:#1f2733;
    color:white;
    font-size:11.5px;
    font-weight:800;
    border-bottom:0;
  }}
  .payment-box {{
    background:#eef3f8;
    border-radius:8px;
    padding:3mm 5mm;
    margin-bottom:3.5mm;
  }}
  .payment-box p {{ margin:0 0 1mm; font-size:9.8px; line-height:1.4; color:#334155; }}
  .payment-box p:last-child {{ margin-bottom:0; }}
  table.signatures {{ width:100%; margin-bottom:0; }}
  table.signatures td {{ width:50%; vertical-align:top; padding-right:8mm; }}
  .sig-title {{
    font-size:9.6px;
    font-weight:800;
    text-transform:uppercase;
    color:#0f172a;
    margin-bottom:1.6mm;
  }}
  .sig {{
    height:12mm;
    border:1px dashed #cbd5e1;
    border-radius:6px;
    display:table;
    width:100%;
  }}
  .sig-inner {{
    display:table-cell;
    vertical-align:middle;
    text-align:center;
    color:#94a3b8;
    font-size:9.8px;
  }}
  .sig img {{ max-width:52mm; max-height:10mm; object-fit:contain; }}
  .doc-footer {{
    margin-top:2.5mm;
    font-size:8.4px;
    line-height:1.4;
    color:#64748b;
    border-top:1px solid #e2e8f0;
    padding-top:2.5mm;
  }}
  @page {{ size:A4; margin:0; }}
  @media print {{
    body {{ background:white; }}
    .toolbar {{ display:none; }}
    .page {{ margin:0; }}
  }}
</style>
</head>
<body>
<div class="toolbar"><button class="print-btn" onclick="window.print()">Imprimer / PDF</button></div>
<main class="page">
  <table class="doc-header">
    <tr>
      <td>
        <div class="company-name">{safe(company["name"])}</div>
        <div class="company-subtitle">{safe(company["subtitle"])}</div>
        <div class="company-line">Adresse : {br(company["address"])}</div>
        <div class="company-line">Tél : {safe(company["phone"])}</div>
        <div class="company-line">Email : {safe(company["email"])}</div>
        <div class="company-line">Site : {safe(company["site"])}</div>
        <div class="company-line">{safe(company["siret"])}</div>
      </td>
      <td class="doc-meta">
        <div class="doc-title">{safe(title)}</div>
        <p><strong>N° {safe(number)}</strong></p>
        <p>Date : {safe(created)}</p>
        <p>{safe(due_label)} : {safe(due or "À réception")}</p>
        <span class="badge">{safe(label_status)}</span>
      </td>
    </tr>
  </table>

  <hr class="accent-line">

  <table class="info-card">
    <tr>
      <td>
        <h3>{safe(client_block_title)}</h3>
        <p><strong>{safe(client_name)}</strong><br>
        {br(client_address) if client_address else "Adresse client à compléter"}<br>
        Contact : {safe(client_contact or client_phone or "à compléter")}<br>
        Email : {safe(client_email or "à compléter")}</p>
      </td>
      <td>
        <h3>Intervention</h3>
        <p><strong>{safe(description)}</strong><br>
        Lieu : à compléter<br>
        Objet : diagnostic, réparation ou remise en service informatique.</p>
      </td>
    </tr>
  </table>

  <section class="technical">
    <h3>Détail technique de l'intervention</h3>
    <ul>
      {''.join(f'<li>{safe(item)}</li>' for item in detail_bullets)}
    </ul>
  </section>

  <table class="items">
    <thead>
      <tr>
        <th>Désignation</th>
        <th class="right">Qté</th>
        <th class="right">Prix unitaire</th>
        <th class="right">Total</th>
      </tr>
    </thead>
    <tbody>
      <tr>
        <td class="designation">
          <strong>{safe(detail_title)}</strong>
          <small>{safe(detail_subtitle)}</small>
        </td>
        <td class="right">1</td>
        <td class="right">{amount:.2f} €</td>
        <td class="right"><strong>{total:.2f} €</strong></td>
      </tr>
    </tbody>
  </table>

  <table class="totals">
    <tr><td>Sous-total</td><td class="value">{amount:.2f} €</td></tr>
    <tr><td>TVA</td><td class="value">Non applicable</td></tr>
    <tr><td>Article 293 B du CGI</td><td class="value">0.00 €</td></tr>
    <tr class="grand"><td>{safe(total_label)}</td><td class="value">{total:.2f} €</td></tr>
  </table>

  <section class="payment-box">
    <h3>Règlement</h3>
    <p>{safe(company["payment_terms"])}</p>
    {extra}
  </section>

  <table class="signatures">
    <tr>
      <td>
        <div class="sig-title">Signature client</div>
        <div class="sig"><div class="sig-inner">{f'<img src="{client_signature_uri}" alt="Signature client">' if client_signature_uri else 'Bon pour accord'}</div></div>
      </td>
      <td>
        <div class="sig-title">Signature Restor-PC</div>
        <div class="sig"><div class="sig-inner">{f'<img src="{signature_uri}" alt="Signature Restor-PC">' if signature_uri else 'Signature Restor-PC'}</div></div>
      </td>
    </tr>
  </table>

  <div class="doc-footer">
    {safe(company["legal"])}<br>
    Merci pour votre confiance. Document généré par Restor-PC RescueGrid.
  </div>
</main>
</body>
</html>"""

def quote_html(quote: Quote) -> str:
    client = quote.client
    intervention = quote.intervention
    desc = _clean_description(quote.description, intervention)
    valid = quote.valid_until.strftime("%d/%m/%Y") if quote.valid_until else ""
    detail_title, detail_subtitle, detail_bullets = _service_presentation(desc)
    return document_html(
        "quote",
        quote.quote_number,
        client.name if client else "Client",
        quote.created_at.strftime("%d/%m/%Y"),
        valid,
        desc,
        quote.amount,
        0.0,
        quote.amount,
        quote.status,
        detail_title=detail_title,
        detail_subtitle=detail_subtitle,
        detail_bullets=detail_bullets,
        client_signature_uri=_client_signature_data_uri(intervention),
        client_email=getattr(client, "email", "") if client else "",
        client_phone=getattr(client, "phone", "") if client else "",
        client_address=getattr(client, "address", "") if client else "",
        client_contact=getattr(client, "contact_name", "") if client else "",
    )


def invoice_html(invoice: Invoice) -> str:
    client = invoice.client
    intervention = invoice.intervention
    desc = _clean_description(invoice.notes, intervention)
    due = invoice.due_date.strftime("%d/%m/%Y") if invoice.due_date else ""
    paid = f"<p><strong>Payé le :</strong> {invoice.paid_at.strftime('%d/%m/%Y')}</p>" if invoice.paid_at else ""
    method = f"<p><strong>Mode de paiement :</strong> {html.escape(invoice.payment_method)}</p>" if invoice.payment_method else ""
    # Le lien est généré à l'avance par l'appelant (ensure_payment_link côté
    # routes_v10.py / main.py) — cette fonction ne fait qu'afficher l'attribut
    # déjà à jour sur l'objet, sans effet de bord ni accès réseau ici.
    payment_link = ""
    if invoice.status not in ("paid", "cancelled") and invoice.stripe_payment_link_url:
        link = html.escape(invoice.stripe_payment_link_url)
        payment_link = (
            f'<p><strong>Payer en ligne par carte bancaire :</strong> '
            f'<a href="{link}">{link}</a></p>'
        )
    detail_title, detail_subtitle, detail_bullets = _service_presentation(desc)
    return document_html(
        "invoice",
        invoice.invoice_number,
        client.name if client else "Client",
        invoice.created_at.strftime("%d/%m/%Y"),
        due,
        desc,
        invoice.amount,
        0.0,
        invoice.amount,
        invoice.status,
        extra=paid + method + payment_link,
        detail_title=detail_title,
        detail_subtitle=detail_subtitle,
        detail_bullets=detail_bullets,
        client_signature_uri=_client_signature_data_uri(intervention),
        client_email=getattr(client, "email", "") if client else "",
        client_phone=getattr(client, "phone", "") if client else "",
        client_address=getattr(client, "address", "") if client else "",
        client_contact=getattr(client, "contact_name", "") if client else "",
    )


def render_document_pdf(html_content: str, filename: str) -> tuple[bytes, str, str, str]:
    """Génère un document PDF à partir d'un contenu HTML — fonction unique utilisée
    à la fois pour la visualisation navigateur (try_pdf_response) et pour les
    pièces jointes email (voir routes_v10.py), afin d'éviter toute divergence.

    Stratégie, dans l'ordre :
      1) Chromium/Chrome headless si présent (moteur à jour : grille/flexbox/
         dégradés CSS complets — le gabarit de document_html() en dépend).
      2) wkhtmltopdf si présent sur le poste (moteur WebKit ancien, gelé depuis
         2012 : ne supporte pas CSS grid/flexbox moderne, à éviter pour ce
         gabarit mais conservé en repli pour compatibilité).
      3) xhtml2pdf (pur Python, toujours disponible via requirements.txt, très
         limité en CSS — dernier repli avant le HTML brut).
      4) HTML imprimable en tout dernier recours si tout échoue.

    Retourne (contenu_binaire, maintype, subtype, nom_de_fichier_final).
    Le contenu est lu en mémoire avant tout nettoyage de fichiers temporaires.
    """
    pdf_name = filename if filename.lower().endswith(".pdf") else f"{Path(filename).stem}.pdf"

    chromium = None
    for cmd in (
        "chromium",
        "chromium-browser",
        "google-chrome",
        "google-chrome-stable",
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    ):
        try:
            subprocess.run([cmd, "--version"], capture_output=True, check=True, timeout=5)
            chromium = cmd
            break
        except (FileNotFoundError, subprocess.SubprocessError, OSError):
            continue

    if chromium:
        with tempfile.TemporaryDirectory() as tmp:
            html_path = Path(tmp) / "document.html"
            pdf_path = Path(tmp) / pdf_name
            html_path.write_text(html_content, encoding="utf-8")
            try:
                subprocess.run(
                    [
                        chromium,
                        "--headless=new",
                        "--disable-gpu",
                        "--no-sandbox",
                        "--disable-dev-shm-usage",
                        "--disable-extensions",
                        "--no-first-run",
                        "--disable-crash-reporter",
                        f"--user-data-dir={tmp}/chrome-profile",
                        "--no-pdf-header-footer",
                        "--print-to-pdf-no-header",
                        "--run-all-compositor-stages-before-draw",
                        "--virtual-time-budget=8000",
                        f"--print-to-pdf={pdf_path}",
                        html_path.as_uri(),
                    ],
                    check=True,
                    timeout=45,
                    capture_output=True,
                )
                if pdf_path.is_file() and pdf_path.stat().st_size > 0:
                    return pdf_path.read_bytes(), "application", "pdf", pdf_name
            except Exception as exc:
                logger.warning("Génération PDF via Chromium impossible : %s", exc)

    wkhtml = None
    for cmd in ("wkhtmltopdf", r"C:\Program Files\wkhtmltopdf\bin\wkhtmltopdf.exe"):
        try:
            subprocess.run([cmd, "--version"], capture_output=True, check=True, timeout=5)
            wkhtml = cmd
            break
        except (FileNotFoundError, subprocess.SubprocessError, OSError):
            continue

    if wkhtml:
        with tempfile.TemporaryDirectory() as tmp:
            html_path = Path(tmp) / "document.html"
            pdf_path = Path(tmp) / pdf_name
            html_path.write_text(html_content, encoding="utf-8")
            try:
                subprocess.run(
                    [
                        wkhtml,
                        # --enable-local-file-access volontairement omis : toutes les images
                        # (logo, signatures) sont déjà embarquées en data URI base64 (voir
                        # _logo_data_uri/_client_signature_data_uri) donc aucun accès fichier
                        # local n'est nécessaire, et l'activer exposerait à une lecture de
                        # fichiers du conteneur si le contenu HTML venait à être manipulé.
                        "--quiet",
                        "--print-media-type",
                        # Le "smart shrinking" (activé par défaut) redimensionne le rendu
                        # pour le faire correspondre à la largeur de page cible en se basant
                        # sur la largeur de viewport initiale (souvent différente des unités
                        # mm utilisées dans le CSS de ce document, calé pixel pour pixel sur
                        # l'A4) : cela provoquait un contenu décalé/rogné sur le côté gauche.
                        # On fige donc une viewport identique à l'A4 (96dpi) et on désactive
                        # ce redimensionnement automatique pour un rendu 1:1 fiable.
                        "--disable-smart-shrinking",
                        "--viewport-size", "794x1123",
                        "--dpi", "96",
                        "--page-size", "A4",
                        "--margin-top", "0",
                        "--margin-right", "0",
                        "--margin-bottom", "0",
                        "--margin-left", "0",
                        str(html_path),
                        str(pdf_path),
                    ],
                    check=True,
                    timeout=45,
                    capture_output=True,
                )
                if pdf_path.is_file() and pdf_path.stat().st_size > 0:
                    return pdf_path.read_bytes(), "application", "pdf", pdf_name
            except Exception as exc:
                logger.warning("Génération PDF via wkhtmltopdf impossible : %s", exc)

    try:
        from xhtml2pdf import pisa  # type: ignore

        output = io.BytesIO()
        pisa_status = pisa.CreatePDF(src=html_content, dest=output, encoding="utf-8")
        pdf_bytes = output.getvalue()
        if not pisa_status.err and pdf_bytes:
            return pdf_bytes, "application", "pdf", pdf_name
    except Exception as exc:
        logger.warning("Génération PDF via xhtml2pdf impossible : %s", exc)

    html_name = f"{Path(pdf_name).stem}.html"
    return html_content.encode("utf-8"), "text", "html", html_name


def try_pdf_response(html_content: str, filename: str) -> Response | HTMLResponse:
    """Réponse HTTP directe (visualisation navigateur) basée sur render_document_pdf."""
    payload, maintype, subtype, final_name = render_document_pdf(html_content, filename)
    if subtype == "pdf":
        return Response(
            content=payload,
            media_type="application/pdf",
            headers={"Content-Disposition": f'inline; filename="{final_name}"'},
        )
    return HTMLResponse(payload.decode("utf-8"))


def generate_ai_summary(intervention: Intervention, folder: Path | None) -> str:
    """Analyse heuristique locale (SMART, Windows, score) — sans API externe."""
    lines = ["=== Analyse Restor-PC RescueGrid ===", ""]
    score = intervention.health_score
    if score is not None:
        if score >= 90:
            lines.append(f"Score santé {score}/100 : machine globalement saine.")
        elif score >= 70:
            lines.append(f"Score santé {score}/100 : surveillance recommandée.")
        else:
            lines.append(f"Score santé {score}/100 : intervention prioritaire.")

    disk = (intervention.disk_risk or "").lower()
    if disk in ("healthy", "ok", "faible"):
        lines.append("Disque : SMART matériel OK — pas de panne hardware détectée.")
    elif disk in ("attention", "warning", "suspect"):
        lines.append("Disque : état suspect — image disque recommandée avant réparation.")
    elif disk:
        lines.append(f"Disque : risque {intervention.disk_risk} — ddrescue avant toute action destructive.")

    if intervention.data_loss_risk:
        lines.append(f"Risque perte données : {intervention.data_loss_risk}.")

    if folder and (folder / "inventory.json").is_file():
        try:
            inv = json.loads((folder / "inventory.json").read_text(encoding="utf-8-sig"))
            health = inv.get("health") or {}
            for key in ("windows_issues", "critical_events", "bsod_count"):
                if health.get(key):
                    lines.append(f"Windows — {key} : {health[key]}")
            disk_risk = inv.get("disk_risk") or {}
            if isinstance(disk_risk, dict) and disk_risk.get("recommendation"):
                lines.append(f"Recommandation : {disk_risk['recommendation']}")
        except (json.JSONDecodeError, OSError):
            pass

    lines.extend([
        "",
        "Cause probable : dégradation progressive ou anomalies système cumulées.",
        "Action : sauvegarde, puis réparation ciblée selon rapport HTML.",
    ])
    return "\n".join(lines)


DEFAULT_PAGE_SIZE = 25


def paginate_query(session, query, page: int = 1, page_size: int = DEFAULT_PAGE_SIZE):
    """Pagine une requête SQLAlchemy Select.

    Retourne (items_de_la_page, page_normalisee, total_pages, total_items).
    `page` est ramené dans les bornes [1, total_pages] pour éviter les pages
    vides ou négatives en cas de paramètre invalide dans l'URL.
    """
    from sqlalchemy import func, select

    total = session.scalar(select(func.count()).select_from(query.subquery())) or 0
    total_pages = max(1, -(-total // page_size))  # ceil division
    page = max(1, min(page, total_pages))
    items = session.scalars(query.limit(page_size).offset((page - 1) * page_size)).all()
    return items, page, total_pages, total


def apply_intervention_filters(query, status: str | None, sort: str | None):
    from .models import Intervention

    if status:
        query = query.where(Intervention.status == status)
    if sort == "score":
        return query.order_by(Intervention.health_score.desc().nulls_last())
    if sort == "date_asc":
        return query.order_by(Intervention.created_at.asc())
    return query.order_by(Intervention.created_at.desc())

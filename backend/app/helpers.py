"""Utilitaires v10 : documents, analyse IA, filtres."""
from __future__ import annotations

import json
import base64
import html
import io
import logging
import subprocess
import tempfile
from pathlib import Path

from fastapi.responses import HTMLResponse, Response

from .models import Intervention, Invoice, Quote

logger = logging.getLogger(__name__)



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
    logo_uri = _logo_data_uri()
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
  :root {{
    --rp-blue:#0969e8;
    --rp-blue2:#0aa5ff;
    --rp-dark:#05080f;
    --rp-dark2:#0b1220;
    --rp-ink:#0f172a;
    --rp-muted:#475569;
    --rp-line:#dbe7f5;
    --rp-soft:#f7fbff;
    --rp-green:#10b981;
  }}
  * {{ box-sizing:border-box; }}
  html, body {{ margin:0; padding:0; }}
  body {{
    font-family:"Segoe UI", Arial, sans-serif;
    color:#0f172a;
    background:linear-gradient(135deg,#070b12,#101827 55%,#07101c);
    -webkit-print-color-adjust:exact;
    print-color-adjust:exact;
  }}
  .toolbar {{
    position:sticky; top:0; z-index:10;
    padding:14px 20px;
    background:rgba(5,8,15,.92);
    border-bottom:1px solid rgba(9,105,232,.28);
    backdrop-filter:blur(8px);
  }}
  .print-btn {{
    border:1px solid rgba(10,165,255,.45);
    border-radius:999px;
    background:linear-gradient(135deg,#0969e8,#0aa5ff);
    color:white;
    padding:10px 16px;
    font-weight:900;
    cursor:pointer;
    box-shadow:0 10px 24px rgba(9,105,232,.28);
  }}
  .preview {{
    padding:28px 20px 50px;
    display:flex;
    justify-content:center;
  }}
  .page {{
    position:relative;
    overflow:hidden;
    width:210mm;
    min-height:297mm;
    background:white;
    box-shadow:0 28px 70px rgba(0,0,0,.45);
    border-radius:0 0 18px 18px;
  }}
  .top {{
    position:relative;
    height:74mm;
    display:grid;
    grid-template-columns:52mm 1fr;
  }}
  .brand-panel {{
    position:relative;
    background:
      radial-gradient(circle at 20% 15%,rgba(9,105,232,.22),transparent 34%),
      linear-gradient(145deg,#05070c 0%,#080d16 58%,#111827 100%);
    color:white;
    padding:7mm 5.5mm;
    overflow:hidden;
  }}
  .brand-panel:after {{
    content:"";
    position:absolute;
    right:-32mm; top:-28mm;
    width:70mm; height:118mm;
    background:linear-gradient(130deg,transparent 0 36%,rgba(9,105,232,.88) 36% 44%,transparent 44%);
    transform:rotate(0deg);
  }}
  .brand-panel img.logo {{
    position:relative;
    z-index:2;
    width:42mm;
    height:auto;
    display:block;
    margin:0 0 3mm;
    filter:drop-shadow(0 8px 16px rgba(0,0,0,.35));
  }}
  .fallback-logo {{
    position:relative; z-index:2;
    font-size:24px; font-weight:950; letter-spacing:1px; margin-bottom:8mm;
  }}
  .company-name {{
    color:#0aa5ff;
    font-weight:950;
    text-transform:uppercase;
    letter-spacing:.6px;
    margin:0 0 2mm;
  }}
  .company-line {{
    position:relative;
    z-index:2;
    display:grid;
    grid-template-columns:5mm 1fr;
    gap:2.4mm;
    margin:1.7mm 0;
    font-size:8.8px;
    line-height:1.25;
    color:#e5edf8;
  }}
  .ico {{
    color:#0aa5ff;
    font-weight:900;
    text-align:center;
  }}
  .doc-panel {{
    position:relative;
    padding:8mm 11mm 0 11mm;
    background:
      linear-gradient(135deg,rgba(9,105,232,.12),transparent 32%),
      white;
  }}
  .doc-panel:before {{
    content:"";
    position:absolute;
    left:-1mm; top:0;
    width:28mm; height:74mm;
    background:white;
    border-bottom-left-radius:42mm;
    box-shadow:-16mm 0 0 white;
  }}
  .doc-panel:after {{
    content:"";
    position:absolute;
    right:11mm; top:0;
    width:14mm; height:48mm;
    background:linear-gradient(180deg,#0aa5ff,#0969e8);
    transform:skewX(-28deg);
    border-radius:0 0 3mm 3mm;
    box-shadow:-4mm 3mm 0 rgba(9,105,232,.18);
  }}
  .doc-meta {{
    position:relative;
    z-index:2;
    text-align:right;
  }}
  .doc-meta h1 {{
    margin:0 0 8mm;
    color:#0969e8;
    font-size:30px;
    line-height:1;
    letter-spacing:.8px;
    text-transform:uppercase;
  }}
  .doc-meta p {{
    margin:3mm 0;
    font-size:11.2px;
    color:#1e293b;
  }}
  .badge {{
    display:inline-block;
    margin-top:3mm;
    padding:2.5mm 5mm;
    border-radius:999px;
    background:#d7f8e9;
    color:#047857;
    font-size:11px;
    font-weight:900;
  }}
  .rule {{
    position:absolute;
    left:52mm;
    right:11mm;
    bottom:0;
    height:1px;
    background:linear-gradient(90deg,#0969e8,rgba(9,105,232,.15));
  }}
  .content {{
    padding:5mm 11mm 23mm;
  }}
  .two {{
    display:grid;
    grid-template-columns:1fr 1fr;
    gap:12mm;
  }}
  .block {{
    border-top:1.5px solid #dbe7f5;
    padding-top:4mm;
    min-height:22mm;
  }}
  .section-title {{
    display:flex;
    align-items:center;
    gap:2.5mm;
    margin:0 0 3mm;
    color:#075cbf;
    font-size:13px;
    font-weight:950;
    text-transform:uppercase;
  }}
  .section-title .mini {{
    width:5mm; height:5mm; border-radius:50%;
    background:linear-gradient(135deg,#0969e8,#0aa5ff);
    color:white;
    display:inline-flex;
    align-items:center;
    justify-content:center;
    font-size:10px;
  }}
  .block p {{
    margin:0;
    font-size:11.2px;
    line-height:1.42;
    color:#1f2937;
  }}
  .block strong {{ color:#111827; }}
  .technical {{
    margin-top:5mm;
  }}
  .technical ul {{
    margin:3mm 0 0;
    padding:0;
    list-style:none;
    display:grid;
    gap:1.5mm;
  }}
  .technical li {{
    position:relative;
    padding-left:7mm;
    font-size:11.2px;
    color:#263445;
  }}
  .technical li:before {{
    content:"✓";
    position:absolute;
    left:0; top:.1mm;
    width:4.2mm; height:4.2mm;
    border-radius:50%;
    background:#0969e8;
    color:white;
    font-size:9px;
    line-height:4.2mm;
    text-align:center;
    font-weight:900;
  }}
  table.items {{
    break-inside:avoid;
    page-break-inside:avoid;
    width:100%;
    border-collapse:collapse;
    margin-top:5mm;
    border:1px solid #dbe7f5;
    box-shadow:0 5px 16px rgba(15,23,42,.04);
  }}
  table.items th {{
    background:linear-gradient(135deg,#075bbb,#0969e8);
    color:white;
    text-transform:uppercase;
    font-size:10.5px;
    letter-spacing:.2px;
    padding:3.2mm;
    text-align:left;
  }}
  table.items td {{
    padding:3.2mm 3mm;
    border-bottom:1px solid #dbe7f5;
    vertical-align:top;
    font-size:11.2px;
  }}
  .right {{ text-align:right; white-space:nowrap; }}
  .designation strong {{
    display:block;
    margin-bottom:2mm;
    color:#0f172a;
  }}
  .designation small {{
    color:#64748b;
    line-height:1.45;
  }}
  .totals {{
    width:88mm;
    margin-left:auto;
    margin-top:0;
    border:1px solid #dbe7f5;
    border-top:0;
  }}
  .totals .row {{
    display:grid;
    grid-template-columns:1fr 32mm;
    align-items:center;
    min-height:7.5mm;
    border-bottom:1px solid #dbe7f5;
    font-size:11.2px;
  }}
  .totals .row span {{
    padding-left:4mm;
  }}
  .totals .row strong {{
    text-align:right;
    padding-right:4mm;
  }}
  .totals .grand {{
    background:linear-gradient(135deg,#075bbb,#0969e8);
    color:white;
    border-bottom:0;
    font-size:16px;
    font-weight:950;
    min-height:10mm;
  }}
  .payment {{
    break-inside:avoid;
    page-break-inside:avoid;
    margin-top:5mm;
    padding-top:4mm;
    border-top:1.5px solid #dbe7f5;
  }}
  .payment p {{
    margin:0;
    font-size:11.5px;
    line-height:1.42;
    color:#334155;
  }}
  .signatures {{
    break-inside:avoid;
    page-break-inside:avoid;
    display:grid;
    grid-template-columns:1fr 1fr;
    gap:12mm;
    margin-top:5mm;
  }}
  .sig-title {{
    color:#075cbf;
    font-weight:950;
    font-size:11.2px;
    text-transform:uppercase;
    margin-bottom:3mm;
  }}
  .sig {{
    height:15.5mm;
    border:1.4px dashed #94a3b8;
    border-radius:4mm;
    display:flex;
    align-items:center;
    justify-content:center;
    color:#94a3b8;
    font-size:11.2px;
    background:linear-gradient(180deg,#ffffff,#fbfdff);
    overflow:hidden;
  }}
  .sig img {{
    max-width:58mm;
    max-height:13.5mm;
    object-fit:contain;
    display:block;
  }}
  .client-signature img {{
    filter:contrast(1.08);
  }}
  .restor-signature span {{
    color:#64748b;
    font-weight:800;
    letter-spacing:.4px;
  }}
  .footer {{
    position:absolute;
    left:0;
    right:0;
    bottom:0;
    height:18mm;
    display:grid;
    grid-template-columns:1fr 1fr;
    color:#e5edf8;
    font-size:10.5px;
    line-height:1.35;
    overflow:hidden;
  }}
  .footer-left {{
    background:#05070c;
    padding:3.2mm 10mm;
    display:flex;
    gap:3mm;
    align-items:center;
  }}
  .footer-right {{
    background:linear-gradient(135deg,#075bbb,#0969e8);
    padding:3.2mm 10mm;
    text-align:right;
    font-weight:800;
    position:relative;
  }}
  .footer-right:before {{
    content:"";
    position:absolute;
    left:-22mm; top:0;
    width:35mm; height:22mm;
    background:#05070c;
    transform:skewX(-35deg);
  }}
  .footer-right span {{
    position:relative;
    z-index:1;
  }}
  @media screen and (max-width:900px) {{
    .page {{ transform:none; width:100%; min-height:auto; border-radius:0; }}
    .top {{ height:auto; grid-template-columns:1fr; }}
    .doc-panel:before,.doc-panel:after,.rule {{ display:none; }}
    .two,.signatures {{ grid-template-columns:1fr; }}
    .footer {{ position:static; grid-template-columns:1fr; height:auto; }}
  }}
  @page {{ size:A4; margin:0; }}
  @media print {{
    body {{ background:white; }}
    .toolbar {{ display:none; }}
    .preview {{ padding:0; }}
    .page {{
      width:190mm;
      min-height:277mm;
      height:277mm;
      margin:10mm auto;
      box-shadow:none;
      border-radius:0;
      overflow:hidden;
    }}
    .top {{ height:68mm; grid-template-columns:48mm 1fr; }}
    .brand-panel {{ padding:5.5mm 4.5mm; }}
    .brand-panel img.logo {{ width:38mm; margin-bottom:2mm; }}
    .company-line {{ font-size:8.2px; margin:1.2mm 0; grid-template-columns:4mm 1fr; }}
    .doc-panel {{ padding:7mm 9mm 0 9mm; }}
    .doc-meta h1 {{ font-size:25px; margin-bottom:6mm; }}
    .content {{ padding:4.5mm 9mm 20mm; }}
    .block {{ min-height:19mm; }}
    .technical {{ margin-top:4mm; }}
    .technical li {{ font-size:10.7px; }}
    table.items {{ margin-top:4mm; }}
    table.items td {{ padding:2.8mm 2.6mm; font-size:10.8px; }}
    .totals {{ width:76mm; }}
    .payment {{ margin-top:4mm; padding-top:4mm; }}
    .signatures {{ margin-top:4mm; }}
    .sig {{ height:14mm; }}
    .footer {{ height:16mm; font-size:8.8px; }}
    .footer-left,.footer-right {{ padding:2.8mm 8mm; }}
  }}
</style>
</head>
<body>
<div class="toolbar"><button class="print-btn" onclick="window.print()">Imprimer / PDF</button></div>
<div class="preview">
<main class="page">
  <section class="top">
    <aside class="brand-panel">
      {f'<img class="logo" src="{logo_uri}" alt="Logo Restor-PC">' if logo_uri else '<div class="fallback-logo">RESTOR-PC</div>'}
      <div class="company-line">
        <div class="ico">●</div>
        <div><div class="company-name">{safe(company["name"])}</div>{safe(company["subtitle"])}</div>
      </div>
      <div class="company-line"><div class="ico">⌖</div><div>{br(company["address"])}</div></div>
      <div class="company-line"><div class="ico">☎</div><div>{safe(company["phone"])}</div></div>
      <div class="company-line"><div class="ico">✉</div><div>{safe(company["email"])}</div></div>
      <div class="company-line"><div class="ico">🌐</div><div>{safe(company["site"])}</div></div>
      <div class="company-line"><div class="ico">▣</div><div>{safe(company["siret"])}</div></div>
    </aside>
    <section class="doc-panel">
      <div class="doc-meta">
        <h1>{safe(title)}</h1>
        <p><strong>N° {safe(number)}</strong></p>
        <p>▣ Date : {safe(created)}</p>
        <p>▣ {safe(due_label)} : {safe(due or "À réception")}</p>
        <span class="badge">{safe(label_status)}</span>
      </div>
    </section>
    <div class="rule"></div>
  </section>

  <section class="content">
    <section class="two">
      <div class="block">
        <div class="section-title"><span class="mini">›</span>{safe(client_block_title)}</div>
        <p><strong>{safe(client_name)}</strong><br>
        {br(client_address) if client_address else "Adresse client à compléter"}<br>
        Contact : {safe(client_contact or client_phone or "à compléter")}<br>
        Email : {safe(client_email or "à compléter")}</p>
      </div>
      <div class="block">
        <div class="section-title"><span class="mini">›</span>INTERVENTION</div>
        <p><strong>{safe(description)}</strong><br>
        Lieu : à compléter<br>
        Objet : diagnostic, réparation ou remise en service informatique.</p>
      </div>
    </section>

    <section class="technical">
      <div class="section-title"><span class="mini">✓</span>DÉTAIL TECHNIQUE DE L'INTERVENTION</div>
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

    <section class="totals">
      <div class="row"><span>Sous-total</span><strong>{amount:.2f} €</strong></div>
      <div class="row"><span>TVA</span><strong>Non applicable</strong></div>
      <div class="row"><span>Article 293 B du CGI</span><strong>0.00 €</strong></div>
      <div class="row grand"><span>{safe(total_label)}</span><strong>{total:.2f} €</strong></div>
    </section>

    <section class="payment">
      <div class="section-title"><span class="mini">€</span>RÈGLEMENT</div>
      <p>{safe(company["payment_terms"])}</p>
      {extra}
    </section>

    <section class="signatures">
      <div>
        <div class="sig-title">Signature client</div>
        <div class="sig client-signature">{f'<img src="{client_signature_uri}" alt="Signature client">' if client_signature_uri else '<span>Bon pour accord</span>'}</div>
      </div>
      <div>
        <div class="sig-title">Signature Restor-PC</div>
        <div class="sig restor-signature">{f'<img src="{signature_uri}" alt="Signature Restor-PC">' if signature_uri else '<span>Signature Restor-PC</span>'}</div>
      </div>
    </section>
  </section>

  <footer class="footer">
    <div class="footer-left">
      <strong>ⓘ</strong>
      <div>{safe(company["legal"])}<br>Document généré par Restor-PC RescueGrid v11.2.</div>
    </div>
    <div class="footer-right">
      <span>Merci pour votre confiance.<br>{safe(company["site"])}</span>
    </div>
  </footer>
</main>
</div>
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
        extra=paid + method,
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
      1) wkhtmltopdf si présent sur le poste (meilleur rendu CSS/print).
      2) xhtml2pdf (pur Python, toujours disponible via requirements.txt).
      3) HTML imprimable en dernier recours si les deux échouent.

    Retourne (contenu_binaire, maintype, subtype, nom_de_fichier_final).
    Le contenu est lu en mémoire avant tout nettoyage de fichiers temporaires.
    """
    pdf_name = filename if filename.lower().endswith(".pdf") else f"{Path(filename).stem}.pdf"

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

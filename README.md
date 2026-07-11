# Restor-PC RescueGrid v12 Stable

Plateforme atelier pour diagnostic PC, suivi d'interventions, clients, machines, devis, factures, rapports et envoi SMTP Infomaniak avec PDF joint.

## Démarrage rapide

```powershell
powershell -ExecutionPolicy Bypass -File install_dependencies.ps1
.\start_dashboard.bat
```

Dashboard : http://localhost:8000

Login par défaut : `admin` / `rescuegrid2026`

## Configuration e-mail Infomaniak

Copier `.env.example` vers `backend/.env`, puis renseigner :

```env
MAIL_ENABLED=true
SMTP_HOST=mail.infomaniak.com
SMTP_PORT=587
SMTP_USER=contact@restor-pc.fr
SMTP_PASSWORD="MOT_DE_PASSE_APPLICATION_INFOMANIAK"
SMTP_SENDER=contact@restor-pc.fr
SMTP_TLS=true
SMTP_SSL=false
```

Utiliser le mot de passe d'application Infomaniak, pas forcément le mot de passe de connexion webmail.

## Fonctionnalités principales

- Import ZIP RescueGrid.
- Dashboard atelier.
- Fiches clients et machines.
- Historique interventions.
- Rapports HTML/PDF.
- Devis et factures premium Restor-PC.
- TVA non applicable, article 293 B du CGI.
- Envoi direct SMTP des devis/factures avec PDF joint.
- Signatures client et Restor-PC.
- Stock pièces, tickets, journal d'activité.
- Outils agent Windows / USB / WinPE.

## Version

v12.3 — espace client (mot de passe / Google / GitHub), planning & RDV, relances devis/factures, export comptable, sauvegarde planifiée, mode multi-poste/Synology, pagination, verrouillage de compte.

# Restor-PC RescueGrid v12 Stable

Plateforme atelier pour diagnostic PC, suivi d'interventions, clients, machines, devis, factures, rapports et envoi SMTP Infomaniak avec PDF joint.

## Démarrage rapide

```powershell
powershell -ExecutionPolicy Bypass -File install_dependencies.ps1
.\start_dashboard.bat
```

Dashboard : http://localhost:8000

Login par défaut : `admin` / mot de passe défini dans `.env` (`ADMIN_PASSWORD`), ou généré aléatoirement et affiché une seule fois dans les logs serveur si `.env` ne le définit pas (voir `docker-compose.yml` pour le dev local, où il reste fixé à `rescuegrid2026` par confort).

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

v12.4.0 — paiement en ligne Stripe sur les factures (webhook de confirmation automatique), relances devis/factures automatisables (cron interne désactivé par défaut), espace client (mot de passe / Google / GitHub), planning & RDV, export comptable, sauvegarde planifiée, mode multi-poste/Synology, pagination, verrouillage de compte, pipeline ADK WinPE automatisé, revue de sécurité complète (secrets, cookies, XSS, en-têtes HTTP, conteneur non-root).

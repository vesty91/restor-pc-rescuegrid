# Restor-PC RescueGrid v12.5.2

Plateforme atelier pour diagnostic PC, suivi d'interventions, clients, machines, devis, factures, rapports et envoi SMTP Infomaniak avec PDF joint.

## Démarrage rapide

Double-clic sur **`Install-RescueGrid.bat`** (installe les dépendances, prépare `.env`, migre la BDD et lance le dashboard).

Ou en ligne de commande :

```powershell
powershell -ExecutionPolicy Bypass -File ps1\Install-RescueGrid.ps1
```

Dashboard : http://localhost:8000  
Page produit : http://localhost:8000/produit

Login par défaut : `admin` / mot de passe défini dans `.env` (`ADMIN_PASSWORD`), ou généré aléatoirement et affiché une seule fois dans les logs serveur si `.env` ne le définit pas. Pour lancer l'app dans Docker en local (SQLite, sans passer par les scripts `.bat`), copier `.env.example` vers `.env` puis `docker compose -f docker-compose.dev.yml up` — ce fichier refuse de démarrer sans `SECRET_KEY`/`ADMIN_PASSWORD` définis dans `.env` (plus de mot de passe par défaut en dur).

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

v12.5.2 — migrations SQLite fiabilisées (FK `0008`, `server_default` alignés), durcissement technique (IP proxy, Alembic, montants Decimal, CD NAS), 2FA admin, sauvegardes alertées, Uptime Kuma, Stripe, espace client, planning & RDV, export comptable, Synology, pipeline ADK WinPE.

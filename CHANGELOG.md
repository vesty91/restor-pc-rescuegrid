# Changelog

## v12.3.1 — Pipeline ADK WinPE automatisé

- Nouveau script `Build-RescueGridWinPE.ps1` : construit automatiquement
  `boot.wim` (copype + ajout WinPE-WMI/NetFx/Scripting/PowerShell/StorageWMI/
  DismCmdlets + personnalisation `startnet.cmd`) et génère optionnellement une
  ISO bootable (`-BuildIso`), à partir d'un Windows ADK installé localement.
- Raccourci `start_build_winpe.bat` et carte dédiée dans `tools.html`.
- Documentation `TECHNICIAN_MANUAL.md` mise à jour (procédure entièrement
  automatisée, remplace les étapes manuelles précédemment reportées).
- Pipeline validé réellement sur poste de build : ADK + add-on WinPE installés
  via winget, `boot.wim` (~480 Mo) et ISO (~535 Mo) générés avec succès.

## v12.3 — Roadmap v12 priorité 3

- Sauvegarde planifiée serveur (SQLite/pg_dump + rotation, scheduler interne) et agent
  (tâche planifiée Windows, lecture auto de `rescuegrid.env`).
- Correction du bug de métadonnées `/upload` (lecture d'`inventory.json` au lieu d'un
  `manifest.json` inexistant) qui cassait la déduplication machine en mode multi-poste.
- Documentation Synology/multi-poste (`docs/SYNOLOGY_DEPLOY.md`) et manuel technicien
  USB/WinPE (`docs/TECHNICIAN_MANUAL.md`).
- Unification des builders de clé USB (`Create-RescueGridUSB.ps1` canonique,
  `Build-RescueGridUSB.ps1` conservé en alias déprécié).

## v12.2 — Roadmap v12 priorité 2

- Espace client sécurisé (mot de passe, connexion Google et GitHub).
- Planning / prise de rendez-vous.
- Relances devis/factures (suggestion manuelle).
- Export comptable (CSV / Excel).
- Pagination sur les listes principales (clients, machines, interventions, tickets…).
- Renforcement de la politique de mot de passe et verrouillage de compte
  (staff et client, par IP et par identifiant).
- Nettoyage du champ TVA mort dans les formulaires devis/factures.

## v12.1 Hardening

- Remplacement de `datetime.utcnow()` par `datetime.now(timezone.utc)`.
- Suppression du log affichant le mot de passe administrateur par défaut.
- Ajout d'un rate limiting simple sur `/login`.
- Ajout du logging backend pour les erreurs auparavant silencieuses.
- Numérotation devis/factures séquentielle journalière (`DEV-YYYYMMDD-0001`, `INV-YYYYMMDD-0001`).
- Début de consolidation production sans modifier le module de résumé local heuristique.


## v12.0 Stable

- Stabilisation de l'envoi SMTP Infomaniak.
- Suppression définitive du fallback Outlook / mailto.
- Chargement robuste de `.env` racine et `backend/.env`.
- Ajout de `python-dotenv` dans les dépendances.
- PDF devis/factures joints automatiquement aux e-mails.
- Nettoyage documentation pour dépôt GitHub.
- Version prête pour branche de développement v12.

## v11.8 Stable

- Devis/factures premium Restor-PC.
- Signature client et signature Restor-PC.
- TVA auto-entrepreneur.
- Dashboard harmonisé.

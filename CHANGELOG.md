# Changelog

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

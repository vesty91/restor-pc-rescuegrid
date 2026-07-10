# Restor-PC RescueGrid v12.1 Hardening

Cette version corrige les points techniques prioritaires hors module IA :

- `datetime.utcnow()` remplacé par `datetime.now(timezone.utc)`.
- Ajout du logging backend.
- Les erreurs auparavant silencieuses sont maintenant journalisées.
- Mot de passe admin par défaut non affiché dans les logs.
- Protection anti brute-force simple sur `/login`.
- Numéros devis/factures générés via compteur séquentiel journalier.
- Préparation à une future refonte Alembic / découpage de `main.py`.

Le module `generate_ai_summary` reste volontairement local et heuristique pour préserver la confidentialité.

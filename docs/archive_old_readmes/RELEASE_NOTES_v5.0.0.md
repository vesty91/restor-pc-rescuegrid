# Release Notes — Restor-PC RescueGrid v5.0.0

**Date :** 2026-06-17
**Version :** v5.0.0 — "Version Business"

---

## Résumé

Cette version transforme Restor-PC RescueGrid en plateforme complète de gestion d'atelier, avec facturation, tickets d'intervention, détection matérielle avancée et outils Linux via WSL.

---

## Nouveautés

### 💰 Facturation (Billing)
- **Modèle Invoice** : numérotation automatique (INV-YYYYMMDD-XXXX)
- **Statuts** : draft, sent, paid, cancelled
- **Calcul automatique** : HT + TVA = TTC
- **Gestion échéances** : date d'échéance, date de paiement
- **Page dédiée** : `/invoices` avec formulaire de création et liste
- **Intégration dashboard** : onglet Factures avec aperçu

### 🎫 Tickets d'intervention
- **Modèle Ticket** : suivi complet des interventions
- **Priorités** : low, medium, high, critical
- **Statuts** : open, in_progress, resolved, closed
- **Suivi temps** : `time_spent_minutes` pour facturation horaire
- **Page dédiée** : `/tickets` avec CRUD complet
- **Association** : automatique avec intervention/client

### 📊 Détection matérielle avancée
- **Fonction `Get-AdvancedHardwareInfo`** :
  - Batterie : charge restante, statut, voltage
  - Carte mère : fabricant, produit, version, serial
  - Slots RAM : capacité, vitesse, part number, emplacement
  - Réseau : adaptateurs physiques, MAC address, vitesse, type
- **Intégré dans l'inventaire** : disponible dans `inventory.json`

### 🌐 Support WSL pour outils Linux
- **ddrescue** : fallback automatique vers WSL si non disponible en natif
- **TestDisk** : fallback WSL
- **PhotoRec** : fallback WSL
- **Détection automatique** : vérifie WSL avant de déclarer l'outil indisponible

### 📤 Export CSV/JSON
- **Paramètre `-ExportCSV`** : génère `inventory.csv`
- **Paramètre `-ExportJSON`** : confirme export JSON (déjà généré par défaut)
- **Fichiers** : `inventory.csv`, `inventory.json`, `blackbox.json`

### 🤖 Mode silencieux
- **Paramètre `-SilentMode`** : pour scripts automatisés
- **Pas d'interaction** : pas de Read-Host, pas de pause
- **Idéal pour** : déploiement en masse, scripts planifiés

### 🖥️ Dashboard amélioré
- **6 onglets** :
  1. Interventions
  2. Clients
  3. Machines
  4. Pièces
  5. **Factures** (nouveau)
  6. **Tickets** (nouveau)
- **Intégration** : factures et tickets dans le dashboard principal
- **Templates responsive** : invoices.html, tickets.html

---

## Fichiers modifiés (v5.0)

```
agent/windows/Invoke-RescueGrid.ps1  ← Get-AdvancedHardwareInfo, WSL, CSV/JSON, SilentMode
backend/app/models.py                 ← Invoice, Ticket + relations
backend/app/main.py                   ← Routes /invoices, /tickets + imports
backend/templates/dashboard.html      ← 6 onglets (dont Factures, Tickets)
backend/templates/invoices.html       ← Nouveau template factures
backend/templates/tickets.html        ← Nouveau template tickets
CHANGELOG.md                          ← v5.0.0 ajoutée
RELEASE_NOTES_v5.0.0.md               ← Ce fichier
```

---

## Commandes

```batch
# Dashboard avec facturation et tickets
start_dashboard.bat
→ http://localhost:8000
→ Login: admin / rescuegrid2026

# Agent avec détection matérielle avancée + WSL
powershell -ExecutionPolicy Bypass -File agent\windows\Invoke-RescueGrid.ps1 -ClientName "Dupont" -BackupRoot "E:\RestorPC" -CreateZip

# Export CSV/JSON
powershell -ExecutionPolicy Bypass -File agent\windows\Invoke-RescueGrid.ps1 -ClientName "Dupont" -BackupRoot "E:\RestorPC" -ExportCSV -ExportJSON

# Mode silencieux (scripts automatisés)
powershell -ExecutionPolicy Bypass -File agent\windows\Invoke-RescueGrid.ps1 -ClientName "Dupont" -BackupRoot "E:\RestorPC" -SilentMode -SkipConsent -CreateZip

# ddrescue via WSL
powershell -ExecutionPolicy Bypass -File agent\windows\Invoke-RescueGrid.ps1 -ClientName "Dupont" -BackupRoot "E:\RestorPC" -CreateZip
# Si disque critical, l'agent utilisera automatiquement WSL pour ddrescue
```

---

## Migration depuis v3.1/v4.x

1. **Base de données** : supprimer `backend/rescuegrid.db` pour recréer les nouvelles tables (Invoice, Ticket)
2. **Dashboard** : 6 onglets au lieu de 4
3. **Agent** : nouvelles options disponibles (WSL, CSV, SilentMode)

---

## Améliorations UX

| Fonctionnalité | Avant | Après |
|----------------|-------|-------|
| Facturation | ❌ | ✅ CRUD complet + numérotation auto |
| Tickets | ❌ | ✅ Priorités + statuts + suivi temps |
| Matériel avancé | ❌ | ✅ Batterie, carte mère, RAM, réseau |
| WSL | ❌ | ✅ Fallback automatique |
| Export CSV | ❌ | ✅ `-ExportCSV` |
| Mode silencieux | ❌ | ✅ `-SilentMode` |
| Dashboard | 4 onglets | 6 onglets |

---

## Prochaines étapes

- [ ] Génération PDF factures
- [ ] Envoi email factures (SMTP)
- [ ] Graphiques statistiques (Chart.js)
- [ ] Multi-utilisateurs avec rôles avancés
- [ ] API REST complète
- [ ] Monitoring serveur (Prometheus/Grafana)

---

*Release Notes générées par Restor-PC RescueGrid v5.0.0*
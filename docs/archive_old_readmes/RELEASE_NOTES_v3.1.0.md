# Release Notes — Restor-PC RescueGrid v3.1.0

**Date :** 2026-06-16
**Version :** v3.1.0 — "Améliorations UX"

---

## Résumé

Cette version apporte des améliorations ergonomiques majeures au dashboard et à l'agent PowerShell, avec un focus sur l'automatisation et l'expérience utilisateur en atelier.

---

## Nouveautés

### 📄 PDF Automatique
- **Génération automatique** par défaut (plus besoin du flag `-GeneratePDF`)
- Option `-NoPDF` pour désactiver si nécessaire
- Rapport signé avec horodatage
- Compatible wkhtmltopdf (fallback gracieux si absent)

### 📊 Export Excel
- Route `/export/interventions.xlsx`
- Export complet : ID, Date, Client, Machine, Titre, Score, Risque disque, Offline, Risque données, Statut
- Compatible Excel/LibreOffice/Google Sheets
- Génération à la volée via openpyxl

### 🔍 Recherche Globale
- Barre de recherche dans le dashboard
- Recherche unifiée dans :
  - Clients (nom)
  - Machines (nom, BIOS Serial)
  - Interventions (titre, nom machine)
  - Pièces (marque, modèle, numéro de série)
- Filtres ILIKE sur tous les champs pertinents
- Résultats affichés dans les onglets correspondants

### 🌓 Dark Mode
- Toggle dans le header du dashboard
- Sauvegarde préférence dans `localStorage`
- Thèmes light/dark avec variables CSS
- Transition fluide entre les thèmes
- Persistance du choix sur toutes les pages

### 🖼️ Logo Personnalisable
- Upload logo via formulaire dashboard
- Stockage dans `storage/logos/logo.png`
- Configuration via `logo_config.json`
- Affichage dans le header (48px de hauteur)
- Remplace le texte "Restor-PC RescueGrid" par le logo

---

## Fichiers modifiés (v3.1)

```
agent/windows/Invoke-RescueGrid.ps1  ← PDF automatique par défaut
backend/requirements.txt             ← openpyxl ajouté
backend/app/main.py                  ← Export Excel + recherche + logo
backend/templates/dashboard.html     ← Dark mode + recherche + logo
CHANGELOG.md                         ← v3.1.0 ajoutée
RELEASE_NOTES_v3.1.0.md              ← Ce fichier
```

---

## Commandes

```batch
# Dashboard avec nouvelles fonctionnalités
start_dashboard.bat
→ http://localhost:8000
→ Login: admin / rescuegrid2026

# Agent avec PDF automatique (pas besoin de -GeneratePDF)
powershell -ExecutionPolicy Bypass -File agent\windows\Invoke-RescueGrid.ps1 -ClientName "Dupont" -BackupRoot "E:\RestorPC" -CreateZip

# Export Excel depuis le dashboard
→ http://localhost:8000/export/interventions.xlsx

# Upload logo personnalisé
→ Dashboard > Formulaire "Logo personnalisable" > Upload image PNG/JPG
```

---

## Migration depuis v3.0.0

1. **PDF automatique** : pas de changement nécessaire, le PDF est généré par défaut
2. **Export Excel** : installer openpyxl (`pip install openpyxl`)
3. **Dark mode** : automatique, pas de configuration nécessaire
4. **Logo** : upload via le dashboard, stocké dans `storage/logos/`

---

## Améliorations UX

| Fonctionnalité | Avant | Après |
|----------------|-------|-------|
| PDF | Flag `-GeneratePDF` requis | Automatique par défaut |
| Export Excel | ❌ | ✅ Route dédiée |
| Recherche | ❌ | ✅ Barre globale |
| Dark mode | ❌ | ✅ Toggle + persistance |
| Logo | ❌ | ✅ Upload personnalisable |

---

*Release Notes générées par Restor-PC RescueGrid v3.1.0*
# Release Notes — Restor-PC RescueGrid v4.0.0

**Date :** 2026-06-16
**Version :** v4.0.0 — "Version Récupération Pro"

---

## Résumé

Cette version transforme Restor-PC RescueGrid en plateforme professionnelle de récupération de données avec intégration d'outils forensic avancés (ddrescue, TestDisk, PhotoRec), authentification sécurisée du dashboard, génération PDF, inventaire atelier, build USB automatique et déploiement Synology Ready.

---

## Nouveautés

### 🖴 Récupération Disque (B1)
- **ddrescue** : image disque avec récupération des secteurs lisibles
- **TestDisk** : analyse et restauration de partitions
- **PhotoRec** : récupération de fichiers par signature
- **Workflow automatique** selon le risque :
  - 🟢 Sain → copie fichiers standard
  - 🟡 Suspect → image disque recommandée
  - 🔴 Critique → ddrescue prioritaire + analyse image
- Blocage automatique de la sauvegarde si disque critical

### 🔐 Authentification Dashboard (B2)
- **JWT** + cookies HttpOnly (8h)
- **RBAC** : rôles admin / technicien
- Page `/login` + `/logout`
- Admin par défaut : `admin` / `rescuegrid2026`
- Journal `last_login` dans la base
- Protection de toutes les routes sensibles

### 📄 PDF Natif (B3)
- Génération PDF via `wkhtmltopdf` (option `-GeneratePDF`)
- Rapport signé avec horodatage
- Fallback gracieux si wkhtmltopdf absent

### 📦 Inventaire Atelier (B4)
- Modèle `Part` : SSD, HDD, RAM, CPU, GPU
- Page `/parts` + CRUD complet
- Suivi stock (quantité, numéro de série, capacité, date d'achat)
- Intégré dans le dashboard (onglet "Pièces")

### 🏗️ Build USB Automatique (B5)
- Script `Build-RescueGridUSB.ps1`
- Formatage, copie scripts, WinPE, smartctl, outils récupération
- Documentation incluse sur la clé
- `autorun.inf` pour lancement automatique

### 🏢 Synology Ready (B6)
- `docker-compose.synology.yml` : PostgreSQL + MinIO + Nginx + backend
- Healthchecks sur tous les services
- Volumes persistants
- pgAdmin inclus pour administration DB
- Variables d'environnement configurables

---

## Fichiers créés (v4.0)

```
backend/app/auth.py                    ← JWT + RBAC
backend/templates/login.html           ← Page login
backend/templates/parts.html           ← Inventaire atelier
agent/windows/Build-RescueGridUSB.ps1  ← Build USB automatique
docker-compose.synology.yml            ← Stack production NAS
RELEASE_NOTES_v4.0.0.md                ← Ce fichier
```

## Fichiers modifiés (v4.0)

```
backend/app/models.py       ← User + Part
backend/app/main.py         ← Auth + Parts routes
backend/templates/dashboard.html ← Onglet Pièces
agent/windows/Invoke-RescueGrid.ps1 ← B1 (ddrescue) + B3 (PDF)
CHANGELOG.md                ← v4.0.0 ajoutée
```

---

## Commandes

```batch
# Dashboard (avec auth)
start_dashboard.bat
→ http://localhost:8000
→ Login: admin / rescuegrid2026

# Agent avec récupération
powershell -ExecutionPolicy Bypass -File agent\windows\Invoke-RescueGrid.ps1 `
    -ClientName "Dupont" -BackupRoot "E:\RestorPC" `
    -GeneratePDF -CreateZip

# Build USB
powershell -ExecutionPolicy Bypass -File agent\windows\Build-RescueGridUSB.ps1 `
    -UsbDriveLetter "E" -IncludeDataRecovery

# Synology
docker-compose -f docker-compose.synology.yml up -d
```

---

## Migration depuis v3.0.0

1. **Base de données** : les nouvelles tables (`user`, `part`) sont créées automatiquement au démarrage
2. **Admin par défaut** : créé automatiquement au premier démarrage
3. **Authentification** : toutes les routes sont maintenant protégées
4. **wkhtmltopdf** : optionnel, installer pour la génération PDF

---

*Release Notes générées par Restor-PC RescueGrid v4.0.0*
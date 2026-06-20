# Release Notes — Restor-PC RescueGrid v3.0.0

**Date :** 2026-06-16
**Version :** v3.0.0 — "Version Atelier"

---

## Résumé

Cette version marque la maturité de la plateforme Restor-PC RescueGrid avec l'ajout de fonctionnalités avancées de diagnostic SMART, d'analyse santé détaillée, de preuve juridique et d'un menu WinPE complet pour les interventions en atelier.

---

## Nouveautés

### 🖴 SMART Avancé
- Détection des températures disques avec seuils colorés (vert < 45°C, orange 45-55°C, rouge > 55°C)
- Analyse des attributs SMART via smartctl : Reallocated Sectors, Current Pending, Uncorrectable Sectors
- Détection et export automatique CrystalDiskInfo CLI
- Export `smart.txt` enrichi avec températures et nombre d'attributs

### 📊 Score Santé Détaillé
- 5 sous-scores pondérés : Disque (25), RAM (10), Windows (30), Drivers (20), Températures (15)
- Jauges CSS visuelles (vert/orange/rouge) dans le rapport HTML
- Risque perte données basé sur le score global
- Détection automatique des problèmes de drivers via les erreurs système

### 🔒 BlackBox Juridique
- Photos avant/après intervention (`-PhotoBefore`, `-PhotoAfter`)
- Signature client numérique (`-SignatureFile`)
- Horodatage signé dans la BlackBox et le rapport HTML
- Consentement client horodaté et enregistré

### ⚠️ Risque Disque Automatique
- Seuils SMART : température > 60°C critique, > 50°C suspect
- Reallocated sectors > 10 critique, > 0 suspect
- Mode recommandé automatique : ddrescue / image disque / sauvegarde
- Blocage automatique de la sauvegarde si disque suspect ou critical

### 🔐 Manifeste Cryptographique
- Nouveau fichier `evidence_manifest.json` avec SHA256 de tous les fichiers
- BIOS Serial, case_id, horodatage

### 🖥️ Dashboard Pro
- Nouveau modèle Machine avec historique par BIOS Serial
- 3 onglets : Interventions, Clients, Machines
- Pages détail client et machine
- Suppression client/intervention
- Association automatique machine à l'import ZIP

### 🏢 WinPE Atelier
- Nouveau script `Start-RescueGrid.ps1` avec menu 9 options
- Diagnostic, sauvegarde, SMART, réparation boot, rapport, réinstallation, offline, vérification système
- Détection automatique des installations Windows
- Mode dégradé si l'agent est absent

### 🚀 Packaging
- `start_agent.bat` : agent rapide avec paramètres
- `start_winpe_menu.bat` : lancement WinPE
- `install_dependencies.ps1` : installation automatique
- `.env.example` : configuration
- `README_DEPLOIEMENT.md` : guide de déploiement
- `CHANGELOG.md` : historique des versions
- `docs/TECHNICIAN_MANUAL.md` : manuel technicien complet
- `docs/CLIENT_GUIDE.md` : guide client

---

## Corrections

- Comparaison `health_status` (entier vs chaîne) dans `Get-DiskRiskAssessment`
- Upload dashboard fonctionne sans nécessiter `-CreateZip`
- Vérification de l'existence du ZIP avant upload
- Gestion robuste de l'absence d'`inventory.json` dans le ZIP importé
- `machine.get("CsName") or None` pour éviter les chaînes vides en base
- Vérification `isinstance()` sur `disk_risk` et `offline_windows`

---

## Sécurité

- Consentement client obligatoire avant toute action
- Logs horodatés de chaque action (`actions_log.txt`)
- Mode lecture seule automatique si disque suspect/critical
- Hash SHA256 de tous les fichiers de preuve
- BlackBox étendue : consentement, photos, signature, mode lecture seule

---

## Fichiers

### Créés (nouveaux)
```
start_agent.bat
start_winpe_menu.bat
install_dependencies.ps1
.env.example
CHANGELOG.md
README_DEPLOIEMENT.md
RELEASE_NOTES_v3.0.0.md
agent/windows/Start-RescueGrid.ps1
backend/templates/client_detail.html
backend/templates/machine_detail.html
docs/TECHNICIAN_MANUAL.md
docs/CLIENT_GUIDE.md
```

### Modifiés
```
agent/windows/Invoke-RescueGrid.ps1  ← v3 complète
backend/app/main.py                  ← Routes + historique + suppression
backend/app/models.py                ← Machine model
backend/templates/dashboard.html     ← 3 onglets
```

---

## Commandes de lancement

```batch
# Dashboard
start_dashboard.bat

# Menu technicien
start_agent_windows.bat

# Agent rapide
start_agent.bat

# WinPE Atelier (depuis clé USB WinPE)
start_winpe_menu.bat
```

---

## Remerciements

Merci à toute l'équipe pour le travail sur cette version majeure.
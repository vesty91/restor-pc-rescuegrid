# Restor-PC RescueGrid v8.0 Atelier

## v6.3 — Correctifs rapport terrain
- SMART températures : parseur enrichi smartctl + fallback WMI.
- EventLogs filtrés : priorité aux sources Disk, NTFS, WHEA, Kernel-Power, VSS, BitLocker, Boot.
- Analyse Windows hors ligne masquée quand non utilisée.
- Recommandation exécutive plus lisible.
- Score Windows recalibré pour éviter de pénaliser les erreurs bénignes.

## v7.0 — Workflow atelier
- Statuts intervention : nouvelle, en_attente, en_cours, termine, livre, facture.
- Étiquette atelier imprimable par intervention.
- Machines à risque dans le dashboard.
- Facture HTML imprimable/PDF navigateur.

## v8.0 — Exploitation NAS
- Backup manuel de la base SQLite.
- Bouton export Excel conservé.
- Dashboard enrichi pour supervision atelier.
- Base prête pour automatisation Synology.

## Lancement

```powershell
powershell -ExecutionPolicy Bypass -File install_dependencies.ps1
.\start_dashboard.bat
```

## Test agent

```powershell
powershell -ExecutionPolicy Bypass -File .\agent\windows\Invoke-RescueGrid.ps1 -ClientName "TEST_V8" -BackupRoot "$PWD" -CreateZip
```

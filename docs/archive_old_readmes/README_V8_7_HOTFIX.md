# Restor-PC RescueGrid v8.7 Hotfix

Correctifs appliqués :
- SMART OK si `Critical Warning = 0` et `Media Errors = 0`.
- Les `Error Information Log Entries` NVMe sont traitées comme historique informatif, pas comme panne.
- ASMT/USB sans SMART n'est pas pénalisé.
- Score recalibré : NTFS ID55 = Attention, mais pas disque mourant.
- Résumé exécutif clarifié et non contradictoire.
- Risque données reste Moyen si NTFS ID55.

Test :
```powershell
powershell -ExecutionPolicy Bypass -File .\agent\windows\Invoke-RescueGrid.ps1 -ClientName "TEST_V8_7" -BackupRoot "$PWD" -CreateZip
```

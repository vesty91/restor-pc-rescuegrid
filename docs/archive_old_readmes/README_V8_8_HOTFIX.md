# Restor-PC RescueGrid v8.8 Hotfix

## Correctifs

- Suppression de la pénalité liée aux `Error Information Log Entries` NVMe.
- Séparation logique entre :
  - **Disque matériel / SMART**
  - **Système de fichiers / NTFS**
- Disque affiché **OK** lorsque SMART est sain, même avec un événement NTFS ID55 isolé.
- NTFS ID55 reste visible comme anomalie filesystem, avec recommandation de sauvegarde avant CHKDSK.
- Score recalibré vers 95-96 sur machine SMART saine.
- Résumé exécutif simplifié et non contradictoire.
- Décision récupération affiche maintenant `Niveau disque matériel` et `Système de fichiers`.

## Test

```powershell
powershell -ExecutionPolicy Bypass -File .\agent\windows\Invoke-RescueGrid.ps1 -ClientName "TEST_V8_8" -BackupRoot "$PWD" -CreateZip
```

## Résultat attendu sur machine testée

- Santé globale : environ 95-96/100
- Disque : OK
- Windows : Attention
- Risque perte données : Moyen si NTFS ID55
- SMART détaillé : SMART OK pour les disques sans Critical Warning ni Media Errors

# Restor-PC RescueGrid v8.9 Hotfix

Correctifs métier appliqués :

- Suppression de la pénalité liée aux `Error Log Entries` NVMe.
- Séparation stricte SMART matériel / NTFS système de fichiers.
- NTFS ID55 classé comme anomalie filesystem Windows, pas panne disque.
- Disque reste OK si SMART est sain (`Critical Warning = 0`, `Media Errors = 0`, santé >= 70%).
- Risque perte données recalibré à `Faible` si SMART matériel est OK.
- Score attendu sur machine saine avec NTFS ID55 isolé : ~97/100.
- Résumé exécutif simplifié et cohérent avec le score.

Test :

```powershell
powershell -ExecutionPolicy Bypass -File .\agent\windows\Invoke-RescueGrid.ps1 -ClientName "TEST_V8_9" -BackupRoot "$PWD" -CreateZip
```

Résultat attendu :
- Santé globale : 97/100 environ
- Disque : OK
- Windows : Attention
- Risque perte données : Faible
- Décision : SMART matériel OK + vérification NTFS après sauvegarde

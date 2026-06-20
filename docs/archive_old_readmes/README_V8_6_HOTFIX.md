# Restor-PC RescueGrid v8.6 Hotfix

Correctifs appliqués :

- Scoring disque plus strict quand NTFS ID 55 est présent.
- Risque perte données passe au minimum à `Moyen` si une anomalie NTFS/disque est détectée.
- SMART Attention si :
  - `Error Information Log Entries` élevé ;
  - usure NVMe élevée ;
  - nombreuses heures de fonctionnement ;
  - température élevée.
- Les boîtiers USB sans SMART ne pénalisent pas le score.
- Résumé exécutif enrichi :
  - SMART disponible ;
  - erreurs média SMART ;
  - disques à surveiller ;
  - recommandation sauvegarde cohérente.
- Jauges colorées selon l'état réel : OK / Attention / Intervention recommandée.

Test :

```powershell
powershell -ExecutionPolicy Bypass -File .\agent\windows\Invoke-RescueGrid.ps1 -ClientName "TEST_V8_6" -BackupRoot "$PWD" -CreateZip
```

Vérifications attendues :

- Score plus réaliste si NTFS ID55 est détecté.
- `Risque perte données : Moyen` si NTFS ID55 est présent.
- Kingston/MP300 affichés en SMART Attention si leur historique est élevé.
- ASMT 2115 reste SMART non disponible sans pénalité disque.

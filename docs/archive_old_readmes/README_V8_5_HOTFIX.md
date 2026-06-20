# Restor-PC RescueGrid v8.5 Hotfix

Correctifs appliqués :

- Heures SMART : correction des séparateurs de milliers (`33 082` n'est plus tronqué en `33`).
- Error Information Log Entries : correction des compteurs SMART (`6 521` n'est plus tronqué en `6`).
- Encodage SMART : normalisation des espaces Unicode / caractères de remplacement dans les sorties smartctl.
- Pondération score : un événement NTFS/Disk force maintenant l'état disque en `Attention` au lieu de `OK`.
- Résumé exécutif : suppression des messages contradictoires quand un événement NTFS est détecté.

Test recommandé :

```powershell
powershell -ExecutionPolicy Bypass -File .\agent\windows\Invoke-RescueGrid.ps1 -ClientName "TEST_V8_5" -BackupRoot "$PWD" -CreateZip
```

Points à vérifier dans `rapport.html` :

- Samsung / Kingston / Force MP300 affichent des heures SMART complètes.
- Les compteurs d'erreurs SMART affichent les valeurs complètes.
- Avec `Ntfs ID 55`, le disque est en `Attention`.
- Le résumé indique une anomalie NTFS et recommande une sauvegarde.

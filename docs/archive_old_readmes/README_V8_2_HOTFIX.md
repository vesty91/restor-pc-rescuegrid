# Restor-PC RescueGrid v8.2 Hotfix

Correctifs appliques :

- Affichage HTML des temperatures SMART : `33°C` au lieu de `°C`.
- Ecriture du rapport HTML en UTF-8 sans BOM via `[System.IO.File]::WriteAllText`.
- Encodage protege pour `Opérateur` et tiret long HTML.
- Correlation NTFS/EventLog disque vers le score disque.
- Correlation NTFS/EventLog disque vers le resume executif.
- Pondération Windows plus precise : erreurs mineures moins penalisees, erreurs disque/boot/WHEA plus importantes.
- Ajout de `scoring_notes` dans `inventory.health`.

Test recommande :

```powershell
powershell -ExecutionPolicy Bypass -File .\agent\windows\Invoke-RescueGrid.ps1 -ClientName "TEST_V8_2" -BackupRoot "$PWD" -CreateZip
```

Verifier dans `rapport.html` :

- Temperatures affichees avec valeur numerique.
- Pas de `OpÃ©rateur`.
- Si evenement NTFS 55 detecte, resume executif et score disque indiquent une surveillance.

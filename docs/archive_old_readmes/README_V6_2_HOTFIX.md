# Restor-PC RescueGrid v6.2 Hotfix

Correctifs ciblés sur le rapport atelier :

- numéro de série BIOS générique remplacé par `Non renseigne par le constructeur` ;
- dates lisibles au format `dd/MM/yyyy HH:mm:ss` ;
- tableau sauvegarde non vide quand aucune sauvegarde n'est lancée ;
- zone signature indique `Signature non fournie` si aucun fichier n'est fourni ;
- résumé exécutif ajouté au rapport ;
- parsing SMART températures amélioré pour smartctl, NVMe et CrystalDiskInfo ;
- détection smartctl/CrystalDiskInfo dans les dossiers outils et Program Files.

Test conseillé :

```powershell
powershell -ExecutionPolicy Bypass -File .\agent\windows\Invoke-RescueGrid.ps1 -ClientName "TEST_V6_2" -BackupRoot "$PWD" -CreateZip
```

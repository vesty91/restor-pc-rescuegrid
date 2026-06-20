# Restor-PC RescueGrid v6.1 Hotfix

Correctifs agent Windows :
- `Invoke-SafeCommand` accepte maintenant les fallbacks `$null`.
- Correction RAM affichée à `0 GB`.
- Correction nom/fabricant/modèle machine via Win32_ComputerSystem, Win32_BaseBoard et Get-ComputerInfo.
- Correction encodage UTF-8 BOM du script PowerShell pour éviter `OpÃ©rateur`.
- Amélioration températures SMART via Get-StorageReliabilityCounter, smartctl `--scan-open` et parsing CrystalDiskInfo.
- Rapport HTML plus robuste avec valeurs fallback propres.

Test conseillé :

```powershell
powershell -ExecutionPolicy Bypass -File .\agent\windows\Invoke-RescueGrid.ps1 -ClientName "TEST_V6_1" -BackupRoot "$PWD" -CreateZip
```

Vérifier :
- RAM non nulle.
- Fabricant / modèle remplis si Windows les fournit.
- Pas d'erreur `Fallback`.
- Encodage correct : `Opérateur`.
- `blackbox.json` non vide.

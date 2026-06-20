# Restor-PC RescueGrid v6.0.1 Hotfix

Correctifs ciblés après test terrain de l'agent Windows.

## Correctifs agent

- `blackbox.json` n'est plus généré vide.
- Correction du bloc `guarantees` BlackBox.
- Correction du calcul des sous-scores santé.
- Protection contre la division par zéro dans les jauges HTML.
- Protection contre les valeurs PowerShell de type tableau dans les scores.
- Correction des variables HTML vides : client, opérateur, machine, Windows, RAM.
- Correction de la récupération fabricant/modèle/nom machine via `Win32_ComputerSystem` + `Win32_OperatingSystem`.
- Tableau températures SMART robuste : affiche la température ou `Non disponible`.
- Ajout d'une validation automatique avant génération du rapport.

## Test recommandé

```powershell
powershell -ExecutionPolicy Bypass -File .\agent\windows\Invoke-RescueGrid.ps1 `
  -ClientName "TEST_HOTFIX" `
  -BackupRoot "$PWD" `
  -CreateZip
```

Vérifier ensuite :

- `blackbox.json` > 0 octet
- `rapport.html` sans jauges vides
- `inventory.json` avec nom/fabricant/modèle
- `evidence_manifest.json` avec hash du BlackBox non vide

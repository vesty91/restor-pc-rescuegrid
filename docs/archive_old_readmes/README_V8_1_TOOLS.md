# Restor-PC RescueGrid v8.1 — Outils SMART embarqués/installables

## Objectif

La v8.1 ajoute la gestion propre des outils externes nécessaires pour les températures SMART :

- smartmontools / `smartctl.exe`
- CrystalDiskInfo CLI / `DiskInfo64.exe`

Les binaires tiers ne sont pas inclus directement dans l'archive pour éviter de redistribuer des logiciels externes sans leurs licences. Le projet fournit donc :

```txt
Install-RescueGridTools.ps1
start_tools_install.bat
tools/README_TOOLS.md
```

## Installation recommandée

Depuis la racine du projet :

```powershell
.\start_tools_install.bat
```

ou :

```powershell
powershell -ExecutionPolicy Bypass -File .\Install-RescueGridTools.ps1
```

Le script tente :

1. Détection de `smartctl`
2. Détection de CrystalDiskInfo
3. Installation via `winget` si absent
4. Test `smartctl --scan`

## Mode portable

Tu peux aussi placer manuellement :

```txt
tools/smartmontools/bin/smartctl.exe
tools/CrystalDiskInfo/DiskInfo64.exe
```

L'agent les détecte automatiquement.

## Vérification

Après installation, relance :

```powershell
powershell -ExecutionPolicy Bypass -File .\agent\windows\Invoke-RescueGrid.ps1 -ClientName "TEST_SMART" -BackupRoot "$PWD" -CreateZip
```

Puis ouvre `smart.txt`.

Tu dois voir :

```txt
Outils detectes:
  smartctl: ...
  CrystalDiskInfo: ...
```

Si les températures restent "Non disponible", cela vient généralement du contrôleur NVMe/USB ou de permissions administrateur.

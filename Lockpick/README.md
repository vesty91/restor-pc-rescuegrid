# Lockpick / Unlocker (hors dépôt public)

Ce dossier **n’est pas versionné** sur le dépôt GitHub public
(`vesty91/restor-pc-rescuegrid`) : outil tiers (licence, taille, image légale).

## Installation locale / atelier

1. Placez votre pack Unlocker / Lockpick dans ce dossier :
   ```
   Lockpick/
     Unlocker.cmd
     Unlocker-Menu.ps1
     Portable/   (binaires x64 si besoin)
     …
   ```
2. Le builder USB le copie s’il est présent :
   ```powershell
   .\agent\windows\winpe\Build-ReadyUSB.ps1
   ```
   → `RescueGrid\Lockpick\` sur la clé.

Sans ce dossier, l’USB se construit quand même ; le menu Unlocker est simplement absent.

## NAS / poste technicien

Gardez une copie privée (NAS partage restreint, clé atelier, coffre) —
**ne pas** committer ni pousser sur un remote public.

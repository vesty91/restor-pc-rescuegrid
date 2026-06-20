# Restor-PC RescueGrid v8.4 Hotfix

Correctifs inclus :

- Mapping SMART sécurisé : plus de fallback aveugle par index.
- Un boîtier USB/SAT avec `Open failed / Error=5` ne récupère plus les données SMART d'un autre disque.
- `smart_available` et `smart_error` ajoutés dans `inventory.json`.
- Parsing numérique SMART amélioré :
  - `Power On Hours: 33 082` devient `33082`
  - `Error Information Log Entries: 6 752` devient `6752`
  - gestion des espaces insécables / séparateurs Unicode.
- Rapport HTML enrichi avec une table **SMART détaillé** :
  - disque Windows
  - périphérique smartctl
  - modèle SMART
  - température
  - usure NVMe
  - heures de fonctionnement
  - données écrites
  - erreurs média
  - état SMART.

Test recommandé :

```powershell
powershell -ExecutionPolicy Bypass -File .\agent\windows\Invoke-RescueGrid.ps1 -ClientName "TEST_V8_4" -BackupRoot "$PWD" -CreateZip
```

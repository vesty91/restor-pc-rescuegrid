# Restor-PC RescueGrid v8.3 Hotfix

Correctifs principaux :

- Mapping smartctl réel par disque via `smartctl --scan`.
- Utilisation correcte des arguments `-d nvme` / `-d sat`.
- Fin du bug où tous les fichiers `smart_disk*.txt` contenaient le même disque.
- Export SMART enrichi : device, modèle, série, température, usure NVMe, heures, données écrites, erreurs média.
- Température HTML affichée avec entité `&#176;C` pour éviter les problèmes `Â°C`.
- CrystalDiskInfo détecté sans faire planter l'agent si la CLI n'est pas exploitable.
- Moteur de scoring contextuel :
  - NTFS ID55 isolé = attention.
  - SMART mauvais / erreurs disque sévères = suspect ou critique.
  - Windows n'est plus massacré par des erreurs DCOM/GamingServices bénignes.
- Nouveau niveau de risque disque : `attention`.
- Recommandations ajustées :
  - `healthy` : copie standard.
  - `attention` : sauvegarde conseillée, CHKDSK uniquement après sauvegarde/image.
  - `suspect` : image disque recommandée.
  - `critical` : ddrescue/image disque prioritaire.

Test recommandé :

```powershell
powershell -ExecutionPolicy Bypass -File .\agent\windows\Invoke-RescueGrid.ps1 -ClientName "TEST_V8_3" -BackupRoot "$PWD" -CreateZip
```

Contrôles attendus :

- `smart_disk0.txt`, `smart_disk1.txt`, etc. doivent correspondre à des disques différents.
- Le rapport doit afficher `33&#176;C` ou équivalent proprement rendu.
- Un NTFS ID55 isolé doit donner `attention`, pas forcément `suspect`.

# Licences — Restor-PC RescueGrid (pack USB / atelier)

Ce fichier accompagne le **pack USB technicien**. Il ne constitue pas un
avis juridique complet ; il documente l’origine des composants embarqués.

## Logiciel Restor-PC RescueGrid

- **Propriétaire / usage atelier Restor-PC** sauf mention contraire dans le
  dépôt GitHub public `vesty91/restor-pc-rescuegrid`.
- Code source application : voir le dépôt et le `CHANGELOG.md` à la version
  du pack.

## Composants système Microsoft (WinPE / ADK)

Si la clé est rendue bootable via Windows ADK + WinPE Addon :

- **Windows PE** et outils ADK : © Microsoft Corporation.
- Conditions d’utilisation : contrat de licence Windows ADK / WinPE
  (usage pour déploiement / maintenance, pas redistribution libre du
  média Windows complet).

## Outils tiers optionnels (`RescueGrid\tools\`)

Selon ce qui a été installé via `ps1\Install-RescueGridTools.ps1` :

| Outil (exemples) | Licence typique |
|------------------|-----------------|
| smartctl (smartmontools) | GPL |
| TestDisk / PhotoRec | GPL |
| Autres utilitaires | Voir le site / archive de chaque éditeur |

Vérifiez les fichiers `COPYING` / `LICENSE` fournis avec chaque binaire
dans `tools\` le cas échéant.

## WinXShell / bureau WinPE

Si `Apply-WinPE-WinXShell` a été appliqué : respecter la licence de
WinXShell / composants associés fournis avec le build WinPE atelier.

## Lockpick / Unlocker (hors dépôt public)

- Le dossier `Lockpick\` **n’est pas** publié sur le dépôt GitHub public
  (voir `Lockpick\README.md` dans le projet source).
- S’il est présent sur cette clé : outil **tiers**, licence éditeur,
  usage strictement local / atelier. Ne pas redistribuer publiquement.

## Intégrité du pack

Voir `SHA256SUMS.txt` à la racine de cette clé (empreintes des fichiers
principaux du pack, hors binaires Lockpick / gros outils).

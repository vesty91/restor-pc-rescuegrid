# Restor-PC RescueGrid v5.0.1 Hotfix

Correctifs inclus :

- correction PowerShell `Test-Path $pipPath -and ...` ;
- sélection automatique de Python 3.12 ou 3.11 via `py -3.12` / `py -3.11` ;
- `start_dashboard.bat` utilise maintenant le Python du venv ;
- lancement Uvicorn via `python -m uvicorn`.

## Lancement

```powershell
powershell -ExecutionPolicy Bypass -File install_dependencies.ps1
.\start_dashboard.bat
```

Dashboard :

```txt
http://localhost:8000
```

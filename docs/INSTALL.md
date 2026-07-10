# Installation

```powershell
powershell -ExecutionPolicy Bypass -File install_dependencies.ps1
Copy-Item .env.example backend\.env
.\start_dashboard.bat
```

Configurer `backend/.env` avant les envois e-mail.

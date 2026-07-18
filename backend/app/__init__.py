"""Initialisation de la configuration RescueGrid.

Charge le .env avant tout sous-module (database, auth, backup, etc.) pour que
les `os.getenv(...)` au niveau module voient bien DATABASE_URL, SECRET_KEY, …
"""

from pathlib import Path

from dotenv import load_dotenv

_BACKEND_DIR = Path(__file__).resolve().parents[1]
_PROJECT_DIR = _BACKEND_DIR.parent

# Configuration générale Docker/local à la racine.
load_dotenv(_PROJECT_DIR / ".env", override=False)

# Configuration locale du backend prioritaire.
load_dotenv(_BACKEND_DIR / ".env", override=True)

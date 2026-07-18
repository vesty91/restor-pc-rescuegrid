"""
app/version.py — Source unique de la version affichee (UI, logs, OpenAPI).

Le fichier VERSION a la racine du projet est la reference unique (voir aussi
CHANGELOG.md). Il est lu directement en developpement natif (VERSION est un
frere du dossier backend/). En conteneur Docker, le contexte de build est
volontairement limite a backend/ (voir docker-compose.synology.yml) — VERSION
n'y est donc pas accessible en COPY, et la valeur est a la place injectee au
build via l'argument APP_VERSION (voir Dockerfile), lu ici depuis la variable
d'environnement du meme nom.
"""
import os
from pathlib import Path


def _read_version() -> str:
    candidate = Path(__file__).resolve().parents[2] / "VERSION"
    try:
        text = candidate.read_text(encoding="utf-8").strip()
        if text:
            return text
    except OSError:
        pass
    # Attention : ARG/ENV Docker vide ("") ne déclenche PAS la valeur par défaut
    # de os.getenv(key, default) — il faut traiter "" comme absent.
    env = (os.getenv("APP_VERSION") or "").strip()
    if env:
        return env
    try:
        baked = Path("/etc/rescuegrid_version").read_text(encoding="utf-8").strip()
        if baked:
            return baked
    except OSError:
        pass
    return "0.0.0-dev"


APP_VERSION: str = _read_version()

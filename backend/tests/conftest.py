"""Fixtures pytest — DATABASE_URL isolée AVANT tout import app.*."""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

# Important : fixer l'URL avant le premier import de app.database (engine créé
# au chargement du module). Sinon les tests pointent vers rescuegrid.db prod/dev.
_TEST_DB = BACKEND / "pytest_unit.db"
if _TEST_DB.exists():
    try:
        _TEST_DB.unlink()
    except OSError:
        pass

os.environ["DATABASE_URL"] = f"sqlite:///{_TEST_DB.as_posix()}"
os.environ.setdefault("SECRET_KEY", "pytest-secret-key")
os.environ.setdefault("ADMIN_PASSWORD", "testadmin2026")
os.environ.pop("UPLOAD_API_KEY", None)
os.chdir(BACKEND)


@pytest.fixture(scope="session")
def migrated_db():
    """Schéma SQLite via alembic upgrade head (même chemin que le démarrage app)."""
    from app.database import init_db

    init_db()
    yield _TEST_DB


@pytest.fixture
def db_session(migrated_db):
    from app.database import SessionLocal

    with SessionLocal() as session:
        yield session
        session.rollback()

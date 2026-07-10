"""
database.py — Restor-PC RescueGrid v12.2
-----------------------------------------
Connexion SQLAlchemy + session factory.

Les migrations de schéma sont gérées par Alembic (alembic/versions/).
Plus aucun _add_column_if_missing ici.

Commandes Alembic utiles (depuis le dossier backend/) :
  alembic upgrade head          → applique toutes les migrations
  alembic downgrade -1          → annule la dernière migration
  alembic revision --autogenerate -m "description"  → génère une nouvelle migration
  alembic history               → liste l'historique des migrations
  alembic current               → révision actuellement appliquée
"""
import logging
import os

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

logger = logging.getLogger(__name__)

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./rescuegrid.db")

# Heroku / Railway fournissent parfois postgres:// — SQLAlchemy exige postgresql://
DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}

engine = create_engine(DATABASE_URL, connect_args=connect_args)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


class Base(DeclarativeBase):
    pass


def init_db() -> None:
    """
    Appelé au démarrage du serveur.

    En développement (SQLite, première installation) : crée les tables si elles
    n'existent pas encore, puis marque la révision initiale comme appliquée
    pour qu'Alembic ne tente pas de re-créer les tables.

    En production (PostgreSQL) : les migrations doivent être appliquées
    manuellement via `alembic upgrade head` avant de démarrer l'application.
    """
    from . import models  # noqa: F401 — enregistre les modèles dans Base.metadata

    if DATABASE_URL.startswith("sqlite"):
        _ensure_sqlite_tables_and_stamp()
    else:
        logger.info(
            "PostgreSQL détecté — assurez-vous d'avoir exécuté `alembic upgrade head` "
            "avant de démarrer l'application."
        )


def _ensure_sqlite_tables_and_stamp() -> None:
    """
    Pour SQLite en dev : crée les tables manquantes via SQLAlchemy (create_all),
    puis stamp Alembic à 'head' pour que `alembic upgrade head` ne plante pas
    sur une BDD déjà peuplée.

    Cette logique est transparente : si les tables existent déjà et qu'Alembic
    est déjà stampé, rien ne se passe.
    """
    try:
        from alembic import command
        from alembic.config import Config
        from alembic.runtime.migration import MigrationContext
        import pathlib

        # Crée les tables si elles n'existent pas (première installation sans Alembic)
        Base.metadata.create_all(engine)

        # Vérifie si Alembic a déjà une révision courante
        with engine.connect() as conn:
            ctx = MigrationContext.configure(conn)
            current_rev = ctx.get_current_revision()

        if current_rev is None:
            # BDD nouvelle ou sans alembic_version → stamp à head
            alembic_cfg_path = pathlib.Path(__file__).resolve().parent.parent / "alembic.ini"
            if alembic_cfg_path.exists():
                cfg = Config(str(alembic_cfg_path))
                command.stamp(cfg, "head")
                logger.info("Alembic stampé à 'head' (première initialisation).")
            else:
                logger.warning(
                    "alembic.ini introuvable — les tables ont été créées via SQLAlchemy "
                    "mais Alembic n'est pas configuré. Ajoutez alembic.ini pour gérer "
                    "les migrations futures."
                )
        else:
            logger.debug("Alembic révision courante : %s", current_rev)

    except ImportError:
        # Alembic non installé : fallback silencieux sur create_all uniquement
        logger.warning(
            "Alembic non installé — utilisation de SQLAlchemy create_all() en fallback. "
            "Installez alembic pour gérer les migrations : pip install alembic"
        )
        Base.metadata.create_all(engine)


def get_session():
    """Générateur de session SQLAlchemy pour l'injection de dépendances FastAPI."""
    with SessionLocal() as session:
        yield session

"""
database.py — Restor-PC RescueGrid v12.5.2
------------------------------------------
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
import pathlib

from sqlalchemy import create_engine, event, inspect
from sqlalchemy.orm import DeclarativeBase, sessionmaker

logger = logging.getLogger(__name__)

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./rescuegrid.db")

# Heroku / Railway fournissent parfois postgres:// — SQLAlchemy exige postgresql://
DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

# requirements.txt installe le driver psycopg (v3), pas psycopg2 : sans le
# suffixe "+psycopg", SQLAlchemy tente d'importer psycopg2 par défaut et
# plante au démarrage avec ModuleNotFoundError.
if DATABASE_URL.startswith("postgresql://"):
    DATABASE_URL = "postgresql+psycopg://" + DATABASE_URL[len("postgresql://"):]

connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}

engine = create_engine(DATABASE_URL, connect_args=connect_args)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


if DATABASE_URL.startswith("sqlite"):
    @event.listens_for(engine, "connect")
    def _sqlite_enable_foreign_keys(dbapi_connection, _connection_record) -> None:
        """
        SQLite n'applique PAS les contraintes de clé étrangère par défaut, même
        si elles sont déclarées dans les modèles — il faut l'activer explicitement
        à chaque nouvelle connexion (ce PRAGMA n'est pas persistant en base).
        Sans ça, supprimer un client/une machine peut laisser des interventions,
        devis ou factures orphelins au lieu d'être bloqué ou traité en cascade
        (voir les relations ondelete définies dans models.py).
        """
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


class Base(DeclarativeBase):
    pass


def init_db() -> None:
    """
    Appelé au démarrage du serveur.

    En développement (SQLite) : si la base est vierge, applique `alembic upgrade
    head` (schéma = migrations, pas create_all + stamp). Si une base existe sans
    alembic_version, refuse de démarrer pour éviter un stamp mensonger.

    En production (PostgreSQL) : les migrations doivent être appliquées
    manuellement / via le déploiement (`alembic upgrade head`) avant démarrage.
    """
    from . import models  # noqa: F401 — enregistre les modèles dans Base.metadata
    from . import rate_limit  # noqa: F401 — rate_limit_hit + scheduler_lock

    if DATABASE_URL.startswith("sqlite"):
        _ensure_sqlite_schema()
    else:
        logger.info(
            "PostgreSQL détecté — assurez-vous d'avoir exécuté `alembic upgrade head` "
            "avant de démarrer l'application."
        )


def _ensure_sqlite_schema() -> None:
    """Initialise ou refuse une base SQLite selon l'état Alembic."""
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())
    is_fresh_db = existing_tables == set() or existing_tables == {"alembic_version"}

    try:
        from alembic import command
        from alembic.config import Config
        from alembic.runtime.migration import MigrationContext

        with engine.connect() as conn:
            ctx = MigrationContext.configure(conn)
            current_rev = ctx.get_current_revision()

        if current_rev is not None:
            logger.debug("Alembic révision courante : %s", current_rev)
            return

        if not is_fresh_db:
            raise RuntimeError(
                "Base SQLite existante (tables: "
                + ", ".join(sorted(existing_tables))
                + ") mais sans révision Alembic connue — arrêt pour éviter un "
                "stamp 'head' mensonger (voir database.py:_ensure_sqlite_schema). "
                "Procédure de conversion : 1) sauvegardez le fichier .db actuel ; "
                "2) déterminez la révision Alembic correspondant réellement au schéma "
                "actuel (comparez les colonnes de vos tables à backend/alembic/versions/) ; "
                "3) lancez `alembic stamp <revision_correspondante>` (PAS 'head') depuis "
                "backend/ ; 4) relancez le serveur — les migrations manquantes "
                "s'appliqueront alors normalement au prochain `alembic upgrade head`."
            )

        alembic_cfg_path = pathlib.Path(__file__).resolve().parent.parent / "alembic.ini"
        if not alembic_cfg_path.exists():
            raise RuntimeError(
                "alembic.ini introuvable — impossible d'initialiser la base SQLite via Alembic."
            )
        cfg = Config(str(alembic_cfg_path))
        command.upgrade(cfg, "head")
        logger.info("Schéma SQLite initialisé via alembic upgrade head (BDD vierge).")

    except ImportError:
        if not is_fresh_db:
            raise RuntimeError(
                "Alembic non installé et base SQLite déjà existante — installez "
                "Alembic (`pip install alembic`) pour permettre une conversion "
                "sûre au lieu de risquer un schéma partiellement à jour."
            )
        logger.warning(
            "Alembic non installé — fallback SQLAlchemy create_all() (schéma potentiellement "
            "légèrement différent des migrations). Installez alembic : pip install alembic"
        )
        Base.metadata.create_all(engine)


def get_session():
    """Générateur de session SQLAlchemy pour l'injection de dépendances FastAPI."""
    with SessionLocal() as session:
        yield session

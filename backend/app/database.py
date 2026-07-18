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

from sqlalchemy import create_engine, event
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

    En développement (SQLite, première installation) : crée les tables si elles
    n'existent pas encore, puis marque la révision initiale comme appliquée
    pour qu'Alembic ne tente pas de re-créer les tables.

    En production (PostgreSQL) : les migrations doivent être appliquées
    manuellement via `alembic upgrade head` avant de démarrer l'application.
    """
    from . import models  # noqa: F401 — enregistre les modèles dans Base.metadata
    from . import rate_limit  # noqa: F401 — rate_limit_hit + scheduler_lock

    if DATABASE_URL.startswith("sqlite"):
        _ensure_sqlite_tables_and_stamp()
    else:
        logger.info(
            "PostgreSQL détecté — assurez-vous d'avoir exécuté `alembic upgrade head` "
            "avant de démarrer l'application."
        )


def _ensure_sqlite_tables_and_stamp() -> None:
    """
    Pour SQLite en dev :
      - BDD réellement vierge (aucune table) : create_all() produit alors
        exactement le schéma courant (colonnes ET contraintes définies dans
        models.py), donc la stamper à 'head' est vrai — c'est le seul cas où
        on le fait automatiquement.
      - BDD existante mais sans alembic_version (ancien fichier .db créé avant
        l'introduction d'Alembic, ou copie d'un ancien poste) : create_all()
        ne fait qu'ajouter les tables manquantes, il n'ajoute JAMAIS de
        colonnes à des tables déjà existantes. Stamper quand même à 'head'
        dans ce cas mentirait sur l'état réel du schéma (Alembic croirait
        toutes les migrations déjà appliquées alors que des colonnes comme
        `user.totp_secret` ou `invoice.stripe_checkout_session_id` peuvent
        manquer) — l'appli planterait plus tard avec des erreurs SQL confuses
        ("no such column") sans qu'`alembic upgrade head` ne puisse jamais
        les corriger (puisqu'il se croirait déjà à jour). On refuse donc de
        démarrer et on affiche la procédure de conversion à suivre.
    """
    import pathlib
    from sqlalchemy import inspect

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
                "stamp 'head' mensonger (voir database.py:_ensure_sqlite_tables_and_stamp). "
                "Procédure de conversion : 1) sauvegardez le fichier .db actuel ; "
                "2) déterminez la révision Alembic correspondant réellement au schéma "
                "actuel (comparez les colonnes de vos tables à backend/alembic/versions/) ; "
                "3) lancez `alembic stamp <revision_correspondante>` (PAS 'head') depuis "
                "backend/ ; 4) relancez le serveur — les migrations manquantes "
                "s'appliqueront alors normalement au prochain `alembic upgrade head`."
            )

        # BDD réellement vierge : create_all() produit le schéma complet et à
        # jour, la stamper à 'head' est donc exact.
        Base.metadata.create_all(engine)

        alembic_cfg_path = pathlib.Path(__file__).resolve().parent.parent / "alembic.ini"
        if alembic_cfg_path.exists():
            cfg = Config(str(alembic_cfg_path))
            command.stamp(cfg, "head")
            logger.info("Alembic stampé à 'head' (première initialisation, BDD vierge).")
        else:
            logger.warning(
                "alembic.ini introuvable — les tables ont été créées via SQLAlchemy "
                "mais Alembic n'est pas configuré. Ajoutez alembic.ini pour gérer "
                "les migrations futures."
            )

    except ImportError:
        # Alembic non installé : fallback sur create_all uniquement, seulement
        # si la BDD est vierge (même raisonnement que ci-dessus).
        if not is_fresh_db:
            raise RuntimeError(
                "Alembic non installé et base SQLite déjà existante — installez "
                "Alembic (`pip install alembic`) pour permettre une conversion "
                "sûre au lieu de risquer un schéma partiellement à jour."
            )
        logger.warning(
            "Alembic non installé — utilisation de SQLAlchemy create_all() en fallback. "
            "Installez alembic pour gérer les migrations : pip install alembic"
        )
        Base.metadata.create_all(engine)


def get_session():
    """Générateur de session SQLAlchemy pour l'injection de dépendances FastAPI."""
    with SessionLocal() as session:
        yield session

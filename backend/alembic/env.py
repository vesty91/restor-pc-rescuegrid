"""
Alembic env.py — Restor-PC RescueGrid
--------------------------------------
Supporte SQLite (dev) et PostgreSQL (prod).
L'URL est lue depuis la variable d'environnement DATABASE_URL,
avec SQLite comme fallback.
"""
import os
import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import engine_from_config, pool

# ── Ajout du dossier backend/app au path pour importer les modèles ──
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.database import Base  # noqa: E402
import app.models  # noqa: E402, F401 — importe tous les modèles pour que Base.metadata les connaisse

# Objet de configuration Alembic (chargé depuis alembic.ini)
config = context.config

# Mise en place du logging depuis alembic.ini
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Métadonnées cibles : Alembic compare ces métadonnées à l'état réel de la BDD
target_metadata = Base.metadata

# ── URL dynamique depuis l'environnement ──
def get_url() -> str:
    url = os.getenv("DATABASE_URL", "sqlite:///./rescuegrid.db")
    # Heroku / Railway fournissent parfois postgres:// — SQLAlchemy exige postgresql://
    return url.replace("postgres://", "postgresql://", 1)


def run_migrations_offline() -> None:
    """
    Mode hors-ligne : génère le SQL sans connexion réelle à la BDD.
    Utile pour auditer les migrations ou les appliquer manuellement.
    """
    url = get_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        # SQLite ne supporte pas ALTER TABLE DROP COLUMN avant 3.35
        render_as_batch=url.startswith("sqlite"),
        compare_type=True,
        compare_server_default=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """
    Mode en ligne : connexion réelle à la BDD et application des migrations.
    """
    # Écrase l'URL dans la config Alembic
    configuration = config.get_section(config.config_ini_section, {})
    configuration["sqlalchemy.url"] = get_url()

    is_sqlite = get_url().startswith("sqlite")

    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            # render_as_batch est OBLIGATOIRE pour SQLite (pas de vrai ALTER TABLE)
            render_as_batch=is_sqlite,
            compare_type=True,
            compare_server_default=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()

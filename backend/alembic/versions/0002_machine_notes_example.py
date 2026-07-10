"""Exemple de migration future — ajout colonne notes sur machine

Revision ID: 0002_machine_notes
Revises: 0001_initial
Create Date: 2026-06-28

Ceci est un exemple de comment ajouter une colonne avec Alembic.
Remplace l'ancien : _add_column_if_missing(conn, "machine", "notes", "ALTER TABLE ...")
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0002_machine_notes"
down_revision: Union[str, None] = "0001_initial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # render_as_batch est activé dans env.py pour SQLite, donc ceci fonctionne
    # aussi bien sur SQLite que sur PostgreSQL, sans code spécifique.
    with op.batch_alter_table("machine") as batch_op:
        batch_op.add_column(sa.Column("notes", sa.String(1000), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("machine") as batch_op:
        batch_op.drop_column("notes")

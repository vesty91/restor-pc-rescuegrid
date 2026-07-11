"""Ajout de la table reminder — traçabilité des relances devis/factures

Revision ID: 0003_reminders
Revises: 0002_machine_notes
Create Date: 2026-07-11
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0003_reminders"
down_revision: Union[str, None] = "0002_machine_notes"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "reminder",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("target_type", sa.String(20), nullable=False),
        sa.Column("target_id", sa.Integer, nullable=False, index=True),
        sa.Column("sent_at", sa.DateTime, nullable=False),
        sa.Column("sent_by_user_id", sa.Integer, sa.ForeignKey("user.id"), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("reminder")

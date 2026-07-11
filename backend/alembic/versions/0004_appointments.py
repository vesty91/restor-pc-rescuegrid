"""Ajout de la table appointment — planning / rendez-vous

Revision ID: 0004_appointments
Revises: 0003_reminders
Create Date: 2026-07-11
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0004_appointments"
down_revision: Union[str, None] = "0003_reminders"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "appointment",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("client_id", sa.Integer, sa.ForeignKey("client.id"), nullable=True),
        sa.Column("intervention_id", sa.Integer, sa.ForeignKey("intervention.id"), nullable=True),
        sa.Column("technician_id", sa.Integer, sa.ForeignKey("user.id"), nullable=True),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("notes", sa.String(1000), nullable=True),
        sa.Column("start_at", sa.DateTime, nullable=False, index=True),
        sa.Column("end_at", sa.DateTime, nullable=True),
        sa.Column("status", sa.String(50), nullable=False, server_default="scheduled"),
        sa.Column("created_at", sa.DateTime, nullable=False),
    )


def downgrade() -> None:
    op.drop_table("appointment")

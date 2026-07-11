"""Ajout des tables client_account et client_oauth_identity — espace client

Revision ID: 0005_client_portal
Revises: 0004_appointments
Create Date: 2026-07-11
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0005_client_portal"
down_revision: Union[str, None] = "0004_appointments"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "client_account",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("client_id", sa.Integer, sa.ForeignKey("client.id"), nullable=False, unique=True),
        sa.Column("email", sa.String(255), nullable=False, unique=True, index=True),
        sa.Column("hashed_password", sa.String(255), nullable=True),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime, nullable=False),
    )
    op.create_table(
        "client_oauth_identity",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("client_account_id", sa.Integer, sa.ForeignKey("client_account.id"), nullable=False),
        sa.Column("provider", sa.String(20), nullable=False),
        sa.Column("provider_user_id", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.UniqueConstraint("provider", "provider_user_id", name="uq_client_oauth_provider_user"),
    )


def downgrade() -> None:
    op.drop_table("client_oauth_identity")
    op.drop_table("client_account")

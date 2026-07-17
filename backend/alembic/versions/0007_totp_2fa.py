"""Ajout de la double authentification (TOTP) sur user

Revision ID: 0007_totp_2fa
Revises: 0006_stripe_invoice_fields
Create Date: 2026-07-17
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0007_totp_2fa"
down_revision: Union[str, None] = "0006_stripe_invoice_fields"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("user", sa.Column("totp_secret", sa.String(64), nullable=True))
    op.add_column("user", sa.Column("totp_enabled", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("user", sa.Column("totp_recovery_codes", sa.String(2000), nullable=True))


def downgrade() -> None:
    op.drop_column("user", "totp_recovery_codes")
    op.drop_column("user", "totp_enabled")
    op.drop_column("user", "totp_secret")

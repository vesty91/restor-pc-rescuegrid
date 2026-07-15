"""Ajout des champs Stripe (lien de paiement) sur invoice

Revision ID: 0006_stripe_invoice_fields
Revises: 0005_client_portal
Create Date: 2026-07-15
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0006_stripe_invoice_fields"
down_revision: Union[str, None] = "0005_client_portal"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("invoice", sa.Column("stripe_checkout_session_id", sa.String(255), nullable=True))
    op.add_column("invoice", sa.Column("stripe_payment_link_url", sa.String(500), nullable=True))
    op.add_column("invoice", sa.Column("stripe_link_expires_at", sa.DateTime, nullable=True))


def downgrade() -> None:
    op.drop_column("invoice", "stripe_link_expires_at")
    op.drop_column("invoice", "stripe_payment_link_url")
    op.drop_column("invoice", "stripe_checkout_session_id")

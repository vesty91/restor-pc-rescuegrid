"""Tables rate_limit_hit + scheduler_lock

Revision ID: 0010_rate_limit
Revises: 0009_money_numeric
Create Date: 2026-07-18
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0010_rate_limit"
down_revision: Union[str, None] = "0009_money_numeric"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "rate_limit_hit",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("bucket", sa.String(length=200), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_rate_limit_hit_bucket", "rate_limit_hit", ["bucket"])
    op.create_index("ix_rate_limit_hit_created_at", "rate_limit_hit", ["created_at"])

    op.create_table(
        "scheduler_lock",
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("holder", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("name"),
    )


def downgrade() -> None:
    op.drop_table("scheduler_lock")
    op.drop_index("ix_rate_limit_hit_created_at", table_name="rate_limit_hit")
    op.drop_index("ix_rate_limit_hit_bucket", table_name="rate_limit_hit")
    op.drop_table("rate_limit_hit")

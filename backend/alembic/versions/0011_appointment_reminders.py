"""0011_appointment_reminders

Revision ID: 0011_appointment_reminders
Revises: 0010_rate_limit
Create Date: 2026-07-21
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0011_appointment_reminders"
down_revision: Union[str, None] = "0010_rate_limit"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # sa.true() (pas DEFAULT 1) : PostgreSQL refuse un entier comme défaut BOOLEAN.
    with op.batch_alter_table("appointment") as batch:
        batch.add_column(
            sa.Column(
                "reminder_opt_in",
                sa.Boolean(),
                nullable=False,
                server_default=sa.true(),
            )
        )
        batch.add_column(sa.Column("sms_reminder_sent_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("appointment") as batch:
        batch.drop_column("sms_reminder_sent_at")
        batch.drop_column("reminder_opt_in")

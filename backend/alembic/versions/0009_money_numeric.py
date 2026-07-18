"""Montants devis/factures/taux : Float -> Numeric(12, 2)

Les colonnes monétaires étaient en FLOAT (binaire), ce qui peut faire dériver
des totaux de quelques centimes. Passage à NUMERIC(12, 2) stocké en Decimal.

Revision ID: 0009_money_numeric
Revises: 0008_fk_ondelete
Create Date: 2026-07-18
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0009_money_numeric"
down_revision: Union[str, None] = "0008_fk_ondelete"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_MONEY = sa.Numeric(12, 2)

_COLUMNS = [
    ("intervention", "labor_rate"),
    ("quote", "amount"),
    ("quote", "tax"),
    ("quote", "total"),
    ("invoice", "amount"),
    ("invoice", "tax"),
    ("invoice", "total"),
]


def upgrade() -> None:
    bind = op.get_bind()
    is_pg = bind.dialect.name == "postgresql"
    for table, column in _COLUMNS:
        if is_pg:
            # PostgreSQL exige souvent USING pour FLOAT -> NUMERIC.
            op.execute(
                sa.text(
                    f'ALTER TABLE "{table}" '
                    f'ALTER COLUMN "{column}" TYPE NUMERIC(12, 2) '
                    f'USING "{column}"::numeric(12, 2)'
                )
            )
        else:
            with op.batch_alter_table(table, schema=None) as batch_op:
                batch_op.alter_column(
                    column,
                    existing_type=sa.Float(),
                    type_=_MONEY,
                    existing_nullable=False,
                )


def downgrade() -> None:
    bind = op.get_bind()
    is_pg = bind.dialect.name == "postgresql"
    for table, column in _COLUMNS:
        if is_pg:
            op.execute(
                sa.text(
                    f'ALTER TABLE "{table}" '
                    f'ALTER COLUMN "{column}" TYPE DOUBLE PRECISION '
                    f'USING "{column}"::double precision'
                )
            )
        else:
            with op.batch_alter_table(table, schema=None) as batch_op:
                batch_op.alter_column(
                    column,
                    existing_type=_MONEY,
                    type_=sa.Float(),
                    existing_nullable=False,
                )

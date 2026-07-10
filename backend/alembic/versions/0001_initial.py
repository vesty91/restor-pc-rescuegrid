"""Migration initiale — création de toutes les tables RescueGrid

Revision ID: 0001_initial
Revises: None
Create Date: 2026-06-28

Cette migration remplace l'ancien système _add_column_if_missing.
Elle crée toutes les tables avec leur schéma complet et définitif.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0001_initial"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── client ──────────────────────────────────────────────────────────
    op.create_table(
        "client",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(255), nullable=False, index=True),
        sa.Column("email", sa.String(255), nullable=True),
        sa.Column("phone", sa.String(80), nullable=True),
        sa.Column("address", sa.String(1000), nullable=True),
        sa.Column("contact_name", sa.String(255), nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False),
    )

    # ── machine ──────────────────────────────────────────────────────────
    op.create_table(
        "machine",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("bios_serial", sa.String(255), nullable=True, index=True),
        sa.Column("machine_name", sa.String(255), nullable=True),
        sa.Column("manufacturer", sa.String(255), nullable=True),
        sa.Column("model", sa.String(255), nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("last_intervention", sa.DateTime, nullable=True),
    )

    # ── user ──────────────────────────────────────────────────────────────
    op.create_table(
        "user",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("username", sa.String(255), nullable=False, unique=True, index=True),
        sa.Column("hashed_password", sa.String(255), nullable=False),
        sa.Column("full_name", sa.String(255), nullable=True),
        sa.Column("email", sa.String(255), nullable=True),
        sa.Column("role", sa.String(80), nullable=False, server_default="technicien"),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="1"),
        sa.Column("last_login", sa.DateTime, nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False),
    )

    # ── part ──────────────────────────────────────────────────────────────
    op.create_table(
        "part",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("part_type", sa.String(80), nullable=False),
        sa.Column("brand", sa.String(255), nullable=True),
        sa.Column("model", sa.String(255), nullable=True),
        sa.Column("serial_number", sa.String(255), nullable=True),
        sa.Column("capacity_gb", sa.Integer, nullable=True),
        sa.Column("quantity", sa.Integer, nullable=False, server_default="1"),
        sa.Column("purchase_date", sa.DateTime, nullable=True),
        sa.Column("notes", sa.String(1024), nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False),
    )

    # ── intervention ──────────────────────────────────────────────────────
    op.create_table(
        "intervention",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("client_id", sa.Integer, sa.ForeignKey("client.id"), nullable=True),
        sa.Column("machine_id", sa.Integer, sa.ForeignKey("machine.id"), nullable=True),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("machine_name", sa.String(255), nullable=True),
        sa.Column("bios_serial", sa.String(255), nullable=True),
        sa.Column("health_score", sa.Integer, nullable=True),
        sa.Column("data_loss_risk", sa.String(80), nullable=True),
        sa.Column("disk_risk", sa.String(80), nullable=True),
        sa.Column("offline_windows", sa.String(80), nullable=True),
        sa.Column("status", sa.String(80), nullable=False, server_default="nouvelle"),
        sa.Column("archive_path", sa.String(1024), nullable=True),
        sa.Column("report_path", sa.String(1024), nullable=True),
        sa.Column("labor_minutes", sa.Integer, nullable=False, server_default="0"),
        sa.Column("labor_rate", sa.Float, nullable=False, server_default="0"),
        sa.Column("signature_path", sa.String(1024), nullable=True),
        sa.Column("ai_summary", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False),
    )

    # ── quote ──────────────────────────────────────────────────────────────
    op.create_table(
        "quote",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("intervention_id", sa.Integer, sa.ForeignKey("intervention.id"), nullable=True),
        sa.Column("client_id", sa.Integer, sa.ForeignKey("client.id"), nullable=True),
        sa.Column("quote_number", sa.String(50), nullable=False, unique=True, index=True),
        sa.Column("description", sa.String(1000), nullable=True),
        sa.Column("amount", sa.Float, nullable=False),
        sa.Column("tax", sa.Float, nullable=False, server_default="0"),
        sa.Column("total", sa.Float, nullable=False),
        sa.Column("status", sa.String(50), nullable=False, server_default="draft"),
        sa.Column("valid_until", sa.DateTime, nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False),
    )

    # ── invoice ────────────────────────────────────────────────────────────
    op.create_table(
        "invoice",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("intervention_id", sa.Integer, sa.ForeignKey("intervention.id"), nullable=True),
        sa.Column("client_id", sa.Integer, sa.ForeignKey("client.id"), nullable=True),
        sa.Column("quote_id", sa.Integer, sa.ForeignKey("quote.id"), nullable=True),
        sa.Column("invoice_number", sa.String(50), nullable=False, unique=True, index=True),
        sa.Column("amount", sa.Float, nullable=False),
        sa.Column("tax", sa.Float, nullable=False, server_default="0"),
        sa.Column("total", sa.Float, nullable=False),
        sa.Column("status", sa.String(50), nullable=False, server_default="draft"),
        sa.Column("due_date", sa.DateTime, nullable=True),
        sa.Column("paid_at", sa.DateTime, nullable=True),
        sa.Column("payment_method", sa.String(80), nullable=True),
        sa.Column("notes", sa.String(1000), nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False),
    )

    # ── ticket ─────────────────────────────────────────────────────────────
    op.create_table(
        "ticket",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("intervention_id", sa.Integer, sa.ForeignKey("intervention.id"), nullable=True),
        sa.Column("client_id", sa.Integer, sa.ForeignKey("client.id"), nullable=True),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("description", sa.String(2000), nullable=True),
        sa.Column("status", sa.String(50), nullable=False, server_default="open"),
        sa.Column("priority", sa.String(50), nullable=False, server_default="medium"),
        sa.Column("time_spent_minutes", sa.Integer, nullable=False, server_default="0"),
        sa.Column("resolved_at", sa.DateTime, nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("updated_at", sa.DateTime, nullable=False),
    )

    # ── intervention_photo ────────────────────────────────────────────────
    op.create_table(
        "intervention_photo",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("intervention_id", sa.Integer, sa.ForeignKey("intervention.id"), nullable=False),
        sa.Column("phase", sa.String(20), nullable=False, server_default="during"),
        sa.Column("file_path", sa.String(1024), nullable=False),
        sa.Column("created_at", sa.DateTime, nullable=False),
    )

    # ── intervention_part ─────────────────────────────────────────────────
    op.create_table(
        "intervention_part",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("intervention_id", sa.Integer, sa.ForeignKey("intervention.id"), nullable=False),
        sa.Column("part_id", sa.Integer, sa.ForeignKey("part.id"), nullable=False),
        sa.Column("quantity", sa.Integer, nullable=False, server_default="1"),
        sa.Column("notes", sa.String(500), nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False),
    )

    # ── activity_log ──────────────────────────────────────────────────────
    op.create_table(
        "activity_log",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.Integer, sa.ForeignKey("user.id"), nullable=True),
        sa.Column("username", sa.String(255), nullable=True),
        sa.Column("action", sa.String(120), nullable=False),
        sa.Column("detail", sa.String(2000), nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False),
    )


def downgrade() -> None:
    # Suppression dans l'ordre inverse des dépendances FK
    op.drop_table("activity_log")
    op.drop_table("intervention_part")
    op.drop_table("intervention_photo")
    op.drop_table("ticket")
    op.drop_table("invoice")
    op.drop_table("quote")
    op.drop_table("intervention")
    op.drop_table("part")
    op.drop_table("user")
    op.drop_table("machine")
    op.drop_table("client")

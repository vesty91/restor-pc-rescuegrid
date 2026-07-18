"""Comportement explicite ON DELETE sur les clés étrangères

Avant cette migration, les FK optionnelles (client_id, machine_id,
intervention_id, ...) n'avaient aucune clause ON DELETE : supprimer un
client/une machine/une intervention laissait des lignes orphelines pointant
vers un id inexistant en SQLite (pas de contrainte appliquée par défaut), et
aurait carrement bloque la suppression sur PostgreSQL (NO ACTION implicite,
dès qu'une ligne dépendante existe). Les deux comportements sont mauvais :
données incohérentes d'un côté, suppression impossible de l'autre.

Cette migration fixe un comportement explicite et cohérent avec les templates
existants (qui affichent déjà tous "Client inconnu" / "—" quand la relation
est absente) :
  - SET NULL pour les références "informatives" optionnelles (client_id,
    machine_id, intervention_id, technician_id, sent_by_user_id, ...) :
    supprimer le parent est autorisé, l'enfant garde son historique mais perd
    la référence.
  - CASCADE pour les lignes qui n'ont aucun sens sans leur parent
    (client_account -> client, client_oauth_identity -> client_account,
    intervention_photo/intervention_part -> intervention).
  - Aucun changement pour intervention_part.part_id : une pièce déjà
    utilisée dans une intervention ne doit pas pouvoir être supprimée
    silencieusement (RESTRICT implicite, voir routes/parts.py qui intercepte
    l'IntegrityError).

Revision ID: 0008_fk_ondelete
Revises: 0007_totp_2fa
Create Date: 2026-07-18
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0008_fk_ondelete"
down_revision: Union[str, None] = "0007_totp_2fa"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# (constraint_name, table, column, ref_table, ref_column, ondelete)
_SET_NULL_FKS = [
    ("intervention_client_id_fkey", "intervention", "client_id", "client", "id"),
    ("intervention_machine_id_fkey", "intervention", "machine_id", "machine", "id"),
    ("quote_intervention_id_fkey", "quote", "intervention_id", "intervention", "id"),
    ("quote_client_id_fkey", "quote", "client_id", "client", "id"),
    ("invoice_intervention_id_fkey", "invoice", "intervention_id", "intervention", "id"),
    ("invoice_client_id_fkey", "invoice", "client_id", "client", "id"),
    ("invoice_quote_id_fkey", "invoice", "quote_id", "quote", "id"),
    ("ticket_intervention_id_fkey", "ticket", "intervention_id", "intervention", "id"),
    ("ticket_client_id_fkey", "ticket", "client_id", "client", "id"),
    ("reminder_sent_by_user_id_fkey", "reminder", "sent_by_user_id", "user", "id"),
    ("appointment_client_id_fkey", "appointment", "client_id", "client", "id"),
    ("appointment_intervention_id_fkey", "appointment", "intervention_id", "intervention", "id"),
    ("appointment_technician_id_fkey", "appointment", "technician_id", "user", "id"),
    ("activity_log_user_id_fkey", "activity_log", "user_id", "user", "id"),
]

_CASCADE_FKS = [
    ("client_account_client_id_fkey", "client_account", "client_id", "client", "id"),
    ("client_oauth_identity_client_account_id_fkey", "client_oauth_identity", "client_account_id", "client_account", "id"),
    ("intervention_photo_intervention_id_fkey", "intervention_photo", "intervention_id", "intervention", "id"),
    ("intervention_part_intervention_id_fkey", "intervention_part", "intervention_id", "intervention", "id"),
]


def _recreate_fk(name: str, table: str, column: str, ref_table: str, ref_column: str, ondelete: str) -> None:
    with op.batch_alter_table(table, schema=None) as batch_op:
        batch_op.drop_constraint(name, type_="foreignkey")
        batch_op.create_foreign_key(name, ref_table, [column], [ref_column], ondelete=ondelete)


def upgrade() -> None:
    for name, table, column, ref_table, ref_column in _SET_NULL_FKS:
        _recreate_fk(name, table, column, ref_table, ref_column, "SET NULL")
    for name, table, column, ref_table, ref_column in _CASCADE_FKS:
        _recreate_fk(name, table, column, ref_table, ref_column, "CASCADE")


def downgrade() -> None:
    for name, table, column, ref_table, ref_column in _CASCADE_FKS:
        _recreate_fk(name, table, column, ref_table, ref_column, "NO ACTION")
    for name, table, column, ref_table, ref_column in _SET_NULL_FKS:
        _recreate_fk(name, table, column, ref_table, ref_column, "NO ACTION")

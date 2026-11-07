"""V3 : comptes employés, responsable des contacts, une boîte mail par personne

Ajoute la table app_user, la table secret (serveur) et les colonnes de rattachement
(mailbox.user_id, contact.owner_id, sequence.owner_id, message.mailbox_id, reminder.user_id).
Rien n'est obligatoire : sur un poste unique, tout reste vide et l'appli marche comme avant.
Écrite pour SQLite ET PostgreSQL ; chaque ajout est sauté s'il existe déjà.

Revision ID: b7c2e9f4a1d3
Revises: a3e8d1c5f7b2
Create Date: 2026-11-07 12:00:00
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b7c2e9f4a1d3"
down_revision: Union[str, Sequence[str], None] = "a3e8d1c5f7b2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    insp = sa.inspect(op.get_bind())
    tables = set(insp.get_table_names())
    if "app_user" not in tables:
        op.create_table(
            "app_user",
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column("auth_id", sa.String(64), unique=True),
            sa.Column("email", sa.String(254), nullable=False, unique=True),
            sa.Column("full_name", sa.String(120), nullable=False, server_default=""),
            sa.Column("role", sa.String(10), nullable=False, server_default="user"),
            sa.Column("active", sa.Boolean, nullable=False, server_default=sa.true()),
            sa.Column("created_at", sa.DateTime, nullable=False),
            sa.Column("last_seen_at", sa.DateTime),
            sa.CheckConstraint("role IN ('admin', 'user')", name="ck_role"),
        )
    if "secret" not in tables:
        op.create_table(
            "secret",
            sa.Column("service", sa.String(100), primary_key=True),
            sa.Column("account", sa.String(254), primary_key=True),
            sa.Column("value", sa.Text, nullable=False),
            sa.Column("updated_at", sa.DateTime, nullable=False),
        )
    for table, col in (("mailbox", "user_id"), ("contact", "owner_id"), ("sequence", "owner_id"),
                       ("message", "mailbox_id"), ("reminder", "user_id")):
        if col not in {c["name"] for c in insp.get_columns(table)}:
            op.add_column(table, sa.Column(col, sa.Integer, nullable=True))
            op.create_index(f"ix_{table}_{col}", table, [col])


def downgrade() -> None:
    pass  # colonnes et tables facultatives : les laisser ne gêne aucune version précédente

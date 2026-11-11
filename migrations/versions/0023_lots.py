"""Repris d'ODDO V3.7 : lots numérotés (chaque import ou recherche de prospects) → variante n de chaque texte.

SQLite ET PostgreSQL ; chaque colonne est sautée si elle existe déjà.

Revision ID: a8c4e2f6d1b9
Revises: f1a7c3e9b5d2
Create Date: 2026-11-11 13:30:00
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a8c4e2f6d1b9"
down_revision: Union[str, Sequence[str], None] = "f1a7c3e9b5d2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _cols(table: str) -> set[str]:
    return {c["name"] for c in sa.inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    if "lot_number" not in _cols("contact"):
        with op.batch_alter_table("contact") as b:
            b.add_column(sa.Column("lot_number", sa.Integer, nullable=True))
            b.create_index("ix_contact_lot_number", ["lot_number"])
    if "lot_number" not in _cols("contact_list"):
        with op.batch_alter_table("contact_list") as b:
            b.add_column(sa.Column("lot_number", sa.Integer, nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("contact_list") as b:
        b.drop_column("lot_number")
    with op.batch_alter_table("contact") as b:
        b.drop_index("ix_contact_lot_number")
        b.drop_column("lot_number")

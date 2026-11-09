"""V3.4 : variantes des textes par fonction / secteur, textes choisis par campagne, texte générique
pour les contacts sans code. content_block.variant_of, campaign.block_map, enrollment.block_code.
SQLite ET PostgreSQL ; chaque colonne est sautée si elle existe déjà.

Revision ID: a6d9f3b1c8e4
Revises: e9b2c5d7f1a3
Create Date: 2026-11-09 17:00:00
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a6d9f3b1c8e4"
down_revision: Union[str, Sequence[str], None] = "e9b2c5d7f1a3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

COLS = [("content_block", "variant_of", sa.String(20)), ("campaign", "block_map", sa.JSON),
        ("enrollment", "block_code", sa.String(30))]


def upgrade() -> None:
    insp = sa.inspect(op.get_bind())
    for table, col, typ in COLS:
        if col not in {c["name"] for c in insp.get_columns(table)}:
            with op.batch_alter_table(table) as b:
                b.add_column(sa.Column(col, typ, nullable=True))


def downgrade() -> None:
    for table, col, _ in reversed(COLS):
        with op.batch_alter_table(table) as b:
            b.drop_column(col)

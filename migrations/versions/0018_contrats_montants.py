"""Contrats : base de calcul (masse salariale, CA…), accessoires, taxes (taxe sur les contrats et
taxe parafiscale) sur chaque contrat. Colonnes sautées si elles existent déjà.

Revision ID: d4e8a1c6b9f2
Revises: c7d3f9a2e6b1
Create Date: 2026-11-09 16:00:00
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "d4e8a1c6b9f2"
down_revision: Union[str, Sequence[str], None] = "c7d3f9a2e6b1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

COLS = [("base_amount", sa.Integer), ("accessories", sa.Integer), ("tax_rate", sa.Float), ("parafiscal_rate", sa.Float)]


def upgrade() -> None:
    have = {c["name"] for c in sa.inspect(op.get_bind()).get_columns("contract")}
    todo = [(n, t) for n, t in COLS if n not in have]
    if todo:
        with op.batch_alter_table("contract") as b:
            for n, t in todo:
                b.add_column(sa.Column(n, t, nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("contract") as b:
        for n, _ in reversed(COLS):
            b.drop_column(n)

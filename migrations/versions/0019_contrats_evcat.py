"""Contrats : EVCAT (taux et plafond) ; le taux des taxes devient le taux total (tableau d'Omar du
09/11). Colonnes sautées si elles existent déjà.

Revision ID: e9b2c5d7f1a3
Revises: d4e8a1c6b9f2
Create Date: 2026-11-09 16:30:00
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "e9b2c5d7f1a3"
down_revision: Union[str, Sequence[str], None] = "d4e8a1c6b9f2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

COLS = [("evcat_rate", sa.Float), ("evcat_cap", sa.Integer)]


def upgrade() -> None:
    have = {c["name"] for c in sa.inspect(op.get_bind()).get_columns("contract")}
    todo = [(n, t) for n, t in COLS if n not in have]
    if todo:
        with op.batch_alter_table("contract") as b:
            for n, t in todo:
                b.add_column(sa.Column(n, t, nullable=True))
    # contrats saisis avec l'ancien modèle (taxe + parafiscale séparées) : taux total = somme
    op.execute("UPDATE contract SET tax_rate = COALESCE(tax_rate, 0) + COALESCE(parafiscal_rate, 0), parafiscal_rate = NULL "
               "WHERE parafiscal_rate IS NOT NULL")


def downgrade() -> None:
    with op.batch_alter_table("contract") as b:
        for n, _ in reversed(COLS):
            b.drop_column(n)

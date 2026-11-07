"""V3 : branche d'assurance d'une séquence (cotations par branche : flotte, AT, prévoyance…)

SQLite ET PostgreSQL ; sautée si la colonne existe déjà.

Revision ID: e6f1b4c8d2a5
Revises: c4d8f2a6b9e1
Create Date: 2026-11-07 21:00:00
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "e6f1b4c8d2a5"
down_revision: Union[str, Sequence[str], None] = "c4d8f2a6b9e1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    cols = {c["name"] for c in sa.inspect(op.get_bind()).get_columns("sequence")}
    if "branch" not in cols:
        op.add_column("sequence", sa.Column("branch", sa.String(40), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("sequence") as b:
        b.drop_column("branch")

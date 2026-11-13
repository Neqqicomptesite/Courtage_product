"""V3.12 : saisie des clients et contrats dans l'appli (relais de DIAMM) : origine, date d'effet, note.

SQLite ET PostgreSQL ; chaque colonne est sautée si elle existe déjà.

Revision ID: f1a9c3e7b5d2
Revises: e2c7a9f4b6d3
Create Date: 2026-11-13 10:30:00
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "f1a9c3e7b5d2"
down_revision: Union[str, Sequence[str], None] = "e2c7a9f4b6d3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    insp = sa.inspect(op.get_bind())
    have = {c["name"] for c in insp.get_columns("portfolio_client")}
    with op.batch_alter_table("portfolio_client") as b:
        if "source" not in have:
            b.add_column(sa.Column("source", sa.String(10), nullable=False, server_default="diamm"))
    have = {c["name"] for c in insp.get_columns("portfolio_contract")}
    with op.batch_alter_table("portfolio_contract") as b:
        if "start_date" not in have:
            b.add_column(sa.Column("start_date", sa.Date, nullable=True))
        if "note" not in have:
            b.add_column(sa.Column("note", sa.Text, nullable=False, server_default=""))
        if "source" not in have:
            b.add_column(sa.Column("source", sa.String(10), nullable=False, server_default="diamm"))


def downgrade() -> None:
    with op.batch_alter_table("portfolio_contract") as b:
        b.drop_column("source")
        b.drop_column("note")
        b.drop_column("start_date")
    with op.batch_alter_table("portfolio_client") as b:
        b.drop_column("source")

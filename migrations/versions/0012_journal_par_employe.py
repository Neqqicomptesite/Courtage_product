"""V3 : journal par employé (event_log.user_id)

Chaque employé ne voit que ses propres événements dans le Journal.
Écrite pour SQLite ET PostgreSQL ; sautée si la colonne existe déjà.

Revision ID: c4d8f2a6b9e1
Revises: b7c2e9f4a1d3
Create Date: 2026-11-07 16:00:00
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c4d8f2a6b9e1"
down_revision: Union[str, Sequence[str], None] = "b7c2e9f4a1d3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    insp = sa.inspect(op.get_bind())
    cols = {c["name"] for c in insp.get_columns("event_log")}
    if "user_id" not in cols:
        op.add_column("event_log", sa.Column("user_id", sa.Integer, nullable=True))
    idx = {i["name"] for i in insp.get_indexes("event_log")}
    if "ix_event_log_user_id" not in idx:
        op.create_index("ix_event_log_user_id", "event_log", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_event_log_user_id", table_name="event_log")
    with op.batch_alter_table("event_log") as b:
        b.drop_column("user_id")

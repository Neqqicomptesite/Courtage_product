"""Dossiers de cotation : relances automatiques (prochaine relance prévue, désactivables).

SQLite ET PostgreSQL ; sauté si les colonnes existent déjà (base neuve créée par create_all).

Revision ID: a3b8d1e5f7c2
Revises: f2a7c9e1b3d4
Create Date: 2026-11-09 09:30:00
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

from app.db import UTCDateTime

revision: str = "a3b8d1e5f7c2"
down_revision: Union[str, Sequence[str], None] = "f2a7c9e1b3d4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    cols = {c["name"] for c in sa.inspect(op.get_bind()).get_columns("quote_insurer")}
    with op.batch_alter_table("quote_insurer") as b:
        if "next_followup_at" not in cols:
            b.add_column(sa.Column("next_followup_at", UTCDateTime, nullable=True))
            b.create_index("ix_quote_insurer_next_followup_at", ["next_followup_at"])
        if "auto_followups" not in cols:
            b.add_column(sa.Column("auto_followups", sa.Boolean, nullable=False, server_default=sa.true()))


def downgrade() -> None:
    with op.batch_alter_table("quote_insurer") as b:
        b.drop_index("ix_quote_insurer_next_followup_at")
        b.drop_column("auto_followups")
        b.drop_column("next_followup_at")

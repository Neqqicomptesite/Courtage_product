"""Réponses aux campagnes : « Marquer comme lu » sans classer (Message.seen_at).

SQLite ET PostgreSQL ; sauté si la colonne existe déjà (base neuve créée par create_all).

Revision ID: b5c2e8f4a1d9
Revises: a3b8d1e5f7c2
Create Date: 2026-11-09 15:00:00
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

from app.db import UTCDateTime

revision: str = "b5c2e8f4a1d9"
down_revision: Union[str, Sequence[str], None] = "a3b8d1e5f7c2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    cols = {c["name"] for c in sa.inspect(op.get_bind()).get_columns("message")}
    if "seen_at" not in cols:
        with op.batch_alter_table("message") as b:
            b.add_column(sa.Column("seen_at", UTCDateTime, nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("message") as b:
        b.drop_column("seen_at")

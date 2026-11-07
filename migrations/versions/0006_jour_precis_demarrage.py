"""relance à un jour précis et démarrage planifié (V2.5)

Revision ID: 6f2d8b4c1e07
Revises: 5e1c0a2b7d93
Create Date: 2026-11-04 10:00:00
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

import app.db

revision: str = "6f2d8b4c1e07"
down_revision: Union[str, Sequence[str], None] = "5e1c0a2b7d93"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Colonnes ajoutées (ALTER TABLE ADD COLUMN) : pas de recréation de table, rien n'est recopié.
    op.add_column("step", sa.Column("weekday", sa.Integer(), nullable=True))
    op.add_column("step", sa.Column("send_time", sa.String(length=5), nullable=True))
    op.add_column("campaign", sa.Column("start_at", app.db.UTCDateTime(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("campaign") as b:
        b.drop_column("start_at")
    with op.batch_alter_table("step") as b:
        b.drop_column("send_time")
        b.drop_column("weekday")

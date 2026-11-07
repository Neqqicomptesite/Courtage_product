"""envoi direct d'une séquence, personnalisation, fonctions et secteurs ajoutés (V2.9)

Revision ID: 8b4f1d6e3a29
Revises: 7a3e9c5d2f18
Create Date: 2026-11-04 12:00:00
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "8b4f1d6e3a29"
down_revision: Union[str, Sequence[str], None] = "7a3e9c5d2f18"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Colonnes ajoutées seulement (ALTER TABLE ADD COLUMN) : aucune table recréée.
    op.add_column("content_block", sa.Column("label", sa.String(length=120), nullable=True))
    op.add_column("campaign", sa.Column("direct", sa.Boolean(), server_default=sa.false(), nullable=False))
    op.add_column("enrollment", sa.Column("overrides", sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("enrollment") as b:
        b.drop_column("overrides")
    with op.batch_alter_table("campaign") as b:
        b.drop_column("direct")
    with op.batch_alter_table("content_block") as b:
        b.drop_column("label")

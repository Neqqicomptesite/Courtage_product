"""Repris d'ODDO V3.7 : carnet d'adresses appris (suggestions À / Cc / Cci).

SQLite ET PostgreSQL ; table sautée si elle existe déjà.

Revision ID: b2d6f8a4c9e3
Revises: a8c4e2f6d1b9
Create Date: 2026-11-11 17:00:00
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

from app.db import UTCDateTime

revision: str = "b2d6f8a4c9e3"
down_revision: Union[str, Sequence[str], None] = "a8c4e2f6d1b9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if "address_book" in sa.inspect(op.get_bind()).get_table_names():
        return
    op.create_table(
        "address_book",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("user_id", sa.Integer, sa.ForeignKey("app_user.id", ondelete="CASCADE"), nullable=True),
        sa.Column("email", sa.String(254), nullable=False),
        sa.Column("name", sa.String(200), nullable=True),
        sa.Column("uses", sa.Integer, nullable=False, server_default="0"),
        sa.Column("last_used", UTCDateTime, nullable=True),
        sa.Column("last_seen", UTCDateTime, nullable=True),
        sa.UniqueConstraint("user_id", "email", name="uq_address_book"),
    )
    op.create_index("ix_address_book_user_id", "address_book", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_address_book_user_id", "address_book")
    op.drop_table("address_book")

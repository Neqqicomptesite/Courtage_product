"""V3.6 : listes de contacts (contact_list, contact_list_member).

SQLite ET PostgreSQL ; chaque table est sautée si elle existe déjà (base neuve créée par create_all).

Revision ID: b8f2d6a4c1e7
Revises: a6d9f3b1c8e4
Create Date: 2026-11-11 11:00:00
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

from app.db import UTCDateTime

revision: str = "b8f2d6a4c1e7"
down_revision: Union[str, Sequence[str], None] = "a6d9f3b1c8e4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    if "contact_list" not in tables:
        op.create_table(
            "contact_list",
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column("org_id", sa.Integer, nullable=False, server_default="1", index=True),
            sa.Column("name", sa.String(120), nullable=False),
            sa.Column("owner_id", sa.Integer, sa.ForeignKey("app_user.id", ondelete="SET NULL"), index=True),
            sa.Column("shared", sa.Boolean, nullable=False, server_default=sa.false()),
            sa.Column("source", sa.String(10), nullable=False, server_default="manual"),
            sa.Column("created_at", UTCDateTime, nullable=False),
            sa.Column("updated_at", UTCDateTime, nullable=False),
            sa.CheckConstraint("source IN ('manual', 'import', 'campaign')", name="ck_source"),
        )
    if "contact_list_member" not in tables:
        op.create_table(
            "contact_list_member",
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column("list_id", sa.Integer, sa.ForeignKey("contact_list.id", ondelete="CASCADE"), nullable=False, index=True),
            sa.Column("contact_id", sa.Integer, sa.ForeignKey("contact.id", ondelete="CASCADE"), nullable=False, index=True),
            sa.Column("added_at", UTCDateTime, nullable=False),
            sa.UniqueConstraint("list_id", "contact_id"),
        )


def downgrade() -> None:
    op.drop_table("contact_list_member")
    op.drop_table("contact_list")

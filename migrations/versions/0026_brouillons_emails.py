"""V3.9.2 : brouillons des emails écrits dans l'appli.

SQLite ET PostgreSQL ; table sautée si elle existe déjà.

Revision ID: d8b3e5a1c7f2
Revises: c7e1a9d3f5b8
Create Date: 2026-11-12 16:00:00
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

from app.db import UTCDateTime

revision: str = "d8b3e5a1c7f2"
down_revision: Union[str, Sequence[str], None] = "c7e1a9d3f5b8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if "mail_draft" in sa.inspect(op.get_bind()).get_table_names():
        return
    op.create_table(
        "mail_draft",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("user_id", sa.Integer, sa.ForeignKey("app_user.id", ondelete="CASCADE"), nullable=True),
        sa.Column("to_addr", sa.Text, nullable=False, server_default=""),
        sa.Column("subject", sa.String(500), nullable=False, server_default=""),
        sa.Column("body", sa.Text, nullable=False, server_default=""),
        sa.Column("data", sa.JSON, nullable=True),
        sa.Column("created_at", UTCDateTime, nullable=False),
        sa.Column("updated_at", UTCDateTime, nullable=False),
    )
    op.create_index("ix_mail_draft_user_id", "mail_draft", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_mail_draft_user_id", "mail_draft")
    op.drop_table("mail_draft")

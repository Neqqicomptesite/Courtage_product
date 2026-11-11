"""Repris d'ODDO V3.7 : recherches de prospects via looot (prospect_search).

SQLite ET PostgreSQL ; la table est sautée si elle existe déjà.

Revision ID: f1a7c3e9b5d2
Revises: b8f2d6a4c1e7
Create Date: 2026-11-11 12:30:00
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

from app.db import UTCDateTime

revision: str = "f1a7c3e9b5d2"
down_revision: Union[str, Sequence[str], None] = "b8f2d6a4c1e7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if "prospect_search" in set(sa.inspect(op.get_bind()).get_table_names()):
        return
    zero = dict(nullable=False, server_default="0")
    op.create_table(
        "prospect_search",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("org_id", sa.Integer, nullable=False, server_default="1", index=True),
        sa.Column("created_by", sa.Integer, sa.ForeignKey("app_user.id", ondelete="SET NULL")),
        sa.Column("criteria", sa.JSON),
        sa.Column("status", sa.String(10), nullable=False, server_default="preview", index=True),
        sa.Column("wanted", sa.Integer, nullable=False, server_default="50"),
        sa.Column("total_found", sa.Integer),
        *(sa.Column(c, sa.Integer, **zero) for c in ("checked", "emails_found", "imported", "skipped_existing",
                                                     "skipped_no_email", "skipped_excluded", "failures")),
        sa.Column("cost_usd", sa.Float, **zero),
        sa.Column("list_id", sa.Integer, sa.ForeignKey("contact_list.id", ondelete="SET NULL")),
        sa.Column("state", sa.JSON),
        sa.Column("error", sa.String(500)),
        sa.Column("created_at", UTCDateTime, nullable=False),
        sa.Column("started_at", UTCDateTime),
        sa.Column("finished_at", UTCDateTime),
        sa.Column("updated_at", UTCDateTime, nullable=False),
        sa.CheckConstraint("status IN ('preview', 'running', 'done', 'stopped', 'failed')", name="ck_status"),
    )


def downgrade() -> None:
    op.drop_table("prospect_search")

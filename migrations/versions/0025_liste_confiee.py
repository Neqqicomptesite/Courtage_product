"""Repris d'ODDO V3.8 : liste confiée à un collègue (qui, quand, message).

SQLite ET PostgreSQL ; chaque colonne est sautée si elle existe déjà.

Revision ID: c7e1a9d3f5b8
Revises: b2d6f8a4c9e3
Create Date: 2026-11-12 09:30:00
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

from app.db import UTCDateTime

revision: str = "c7e1a9d3f5b8"
down_revision: Union[str, Sequence[str], None] = "b2d6f8a4c9e3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    have = {c["name"] for c in sa.inspect(op.get_bind()).get_columns("contact_list")}
    with op.batch_alter_table("contact_list") as b:
        if "assigned_by" not in have:
            b.add_column(sa.Column("assigned_by", sa.Integer, nullable=True))
            b.create_foreign_key("fk_contact_list_assigned_by", "app_user", ["assigned_by"], ["id"], ondelete="SET NULL")
        if "assigned_at" not in have:
            b.add_column(sa.Column("assigned_at", UTCDateTime, nullable=True))
        if "assign_note" not in have:
            b.add_column(sa.Column("assign_note", sa.String(2000), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("contact_list") as b:
        b.drop_constraint("fk_contact_list_assigned_by", type_="foreignkey")
        b.drop_column("assign_note")
        b.drop_column("assigned_at")
        b.drop_column("assigned_by")

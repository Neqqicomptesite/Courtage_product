"""V3.10 : portefeuille clients (import DIAMM) : clients consolidés et leurs contrats.

SQLite ET PostgreSQL ; tables sautées si elles existent déjà.

Revision ID: e2c7a9f4b6d3
Revises: d8b3e5a1c7f2
Create Date: 2026-11-12 16:30:00
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

from app.db import UTCDateTime

revision: str = "e2c7a9f4b6d3"
down_revision: Union[str, Sequence[str], None] = "d8b3e5a1c7f2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    have = set(sa.inspect(op.get_bind()).get_table_names())
    if "portfolio_client" not in have:
        op.create_table(
            "portfolio_client",
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column("org_id", sa.Integer, nullable=False, server_default="1"),
            sa.Column("key", sa.String(255), nullable=False),
            sa.Column("name", sa.String(255), nullable=False),
            sa.Column("segment", sa.String(12), nullable=False, server_default="particulier"),
            sa.Column("email", sa.String(254), nullable=True),
            sa.Column("phones", sa.JSON, nullable=True),
            sa.Column("note", sa.Text, nullable=False, server_default=""),
            sa.Column("contact_id", sa.Integer, sa.ForeignKey("contact.id", ondelete="SET NULL"), nullable=True),
            sa.Column("seen_at", UTCDateTime, nullable=True),
            sa.Column("created_at", UTCDateTime, nullable=False),
            sa.Column("updated_at", UTCDateTime, nullable=False),
            sa.UniqueConstraint("org_id", "key", name="uq_portfolio_client_key"),
            sa.CheckConstraint("segment IN ('particulier', 'pro')", name="ck_segment"),
        )
        op.create_index("ix_portfolio_client_org_id", "portfolio_client", ["org_id"])
        op.create_index("ix_portfolio_client_contact_id", "portfolio_client", ["contact_id"])
    if "portfolio_contract" not in have:
        op.create_table(
            "portfolio_contract",
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column("org_id", sa.Integer, nullable=False, server_default="1"),
            sa.Column("client_id", sa.Integer, sa.ForeignKey("portfolio_client.id", ondelete="CASCADE"), nullable=False),
            sa.Column("policy", sa.String(80), nullable=False),
            sa.Column("insurer", sa.String(120), nullable=False),
            sa.Column("category", sa.String(120), nullable=False, server_default=""),
            sa.Column("branch", sa.String(120), nullable=False, server_default=""),
            sa.Column("family", sa.String(60), nullable=False, server_default=""),
            sa.Column("fixed_term", sa.Boolean, nullable=False, server_default=sa.false()),
            sa.Column("fleet", sa.Boolean, nullable=False, server_default=sa.false()),
            sa.Column("cancelled", sa.Boolean, nullable=False, server_default=sa.false()),
            sa.Column("cancelled_on", sa.Date, nullable=True),
            sa.Column("premium", sa.Float, nullable=True),
            sa.Column("due_date", sa.Date, nullable=True),
            sa.Column("raw", sa.JSON, nullable=True),
            sa.Column("seen_at", UTCDateTime, nullable=True),
            sa.Column("created_at", UTCDateTime, nullable=False),
            sa.UniqueConstraint("org_id", "insurer", "policy", name="uq_portfolio_contract"),
        )
        op.create_index("ix_portfolio_contract_org_id", "portfolio_contract", ["org_id"])
        op.create_index("ix_portfolio_contract_client_id", "portfolio_contract", ["client_id"])
    if "portfolio_call" not in have:
        op.create_table(
            "portfolio_call",
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column("org_id", sa.Integer, nullable=False, server_default="1"),
            sa.Column("client_id", sa.Integer, sa.ForeignKey("portfolio_client.id", ondelete="CASCADE"), nullable=False),
            sa.Column("user_id", sa.Integer, sa.ForeignKey("app_user.id", ondelete="SET NULL"), nullable=True),
            sa.Column("rule", sa.String(60), nullable=True),
            sa.Column("outcome", sa.String(20), nullable=False),
            sa.Column("note", sa.Text, nullable=False, server_default=""),
            sa.Column("callback_on", sa.Date, nullable=True),
            sa.Column("callback_done", sa.Boolean, nullable=False, server_default=sa.false()),
            sa.Column("created_at", UTCDateTime, nullable=False),
            sa.CheckConstraint("outcome IN ('interested', 'callback', 'not_interested', 'no_answer', 'wrong_number', 'done')",
                               name="ck_outcome"),
        )
        op.create_index("ix_portfolio_call_org_id", "portfolio_call", ["org_id"])
        op.create_index("ix_portfolio_call_client_id", "portfolio_call", ["client_id"])
        op.create_index("ix_portfolio_call_user_id", "portfolio_call", ["user_id"])


def downgrade() -> None:
    op.drop_table("portfolio_call")
    op.drop_table("portfolio_contract")
    op.drop_table("portfolio_client")

"""Contrats et échéances (table contract) et lien rappel → contrat (reminder.contract_id).

SQLite ET PostgreSQL ; chaque élément est sauté s'il existe déjà (base PostgreSQL neuve créée
par create_all puis marquée « head »).

Revision ID: c7d3f9a2e6b1
Revises: b5c2e8f4a1d9
Create Date: 2026-11-09 13:00:00
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

from app.db import UTCDateTime

revision: str = "c7d3f9a2e6b1"
down_revision: Union[str, Sequence[str], None] = "b5c2e8f4a1d9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    insp = sa.inspect(op.get_bind())
    if "contract" not in set(insp.get_table_names()):
        op.create_table(
            "contract",
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column("org_id", sa.Integer, nullable=False, server_default="1", index=True),
            sa.Column("client_name", sa.String(255), nullable=False),
            sa.Column("company_id", sa.Integer, sa.ForeignKey("company.id", ondelete="SET NULL"), index=True),
            sa.Column("contact_id", sa.Integer, sa.ForeignKey("contact.id", ondelete="SET NULL"), index=True),
            sa.Column("insurer_id", sa.Integer, sa.ForeignKey("company.id", ondelete="SET NULL"), index=True),
            sa.Column("insurer_name", sa.String(120), nullable=False, server_default=""),
            sa.Column("branch", sa.String(40), nullable=False),
            sa.Column("policy_number", sa.String(60), nullable=False, server_default=""),
            sa.Column("premium", sa.Integer),
            sa.Column("rate", sa.String(40)),
            sa.Column("commission_rate", sa.Float),
            sa.Column("start_date", sa.Date),
            sa.Column("end_date", sa.Date, nullable=False, index=True),
            sa.Column("notice_days", sa.Integer, nullable=False, server_default="60"),
            sa.Column("tacit", sa.Boolean, nullable=False, server_default=sa.true()),
            sa.Column("status", sa.String(10), nullable=False, server_default="active", index=True),
            sa.Column("end_reason", sa.String(255)),
            sa.Column("owner_id", sa.Integer, sa.ForeignKey("app_user.id", ondelete="SET NULL"), index=True),
            sa.Column("quote_case_id", sa.Integer, sa.ForeignKey("quote_case.id", ondelete="SET NULL"), index=True),
            sa.Column("renewal_case_id", sa.Integer, sa.ForeignKey("quote_case.id", ondelete="SET NULL"), index=True),
            sa.Column("previous_id", sa.Integer, sa.ForeignKey("contract.id", ondelete="SET NULL")),
            sa.Column("notes", sa.Text, nullable=False, server_default=""),
            sa.Column("history", sa.JSON),
            sa.Column("created_at", UTCDateTime, nullable=False),
            sa.Column("updated_at", UTCDateTime, nullable=False),
            sa.CheckConstraint("status IN ('active', 'renewing', 'ended')", name="ck_status"),
        )
    cols = {c["name"] for c in insp.get_columns("reminder")}
    if "contract_id" not in cols:
        with op.batch_alter_table("reminder") as b:
            b.add_column(sa.Column("contract_id", sa.Integer, nullable=True))
            b.create_foreign_key("fk_reminder_contract", "contract", ["contract_id"], ["id"], ondelete="CASCADE")
            b.create_index("ix_reminder_contract_id", ["contract_id"])


def downgrade() -> None:
    with op.batch_alter_table("reminder") as b:
        b.drop_index("ix_reminder_contract_id")
        b.drop_constraint("fk_reminder_contract", type_="foreignkey")
        b.drop_column("contract_id")
    op.drop_table("contract")

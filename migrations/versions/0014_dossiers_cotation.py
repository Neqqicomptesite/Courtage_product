"""Cotalis, phase 1 : dossiers de cotation (quote_case, quote_insurer, quote_event, quote_file)
et lien rappel → dossier (reminder.quote_case_id).

SQLite ET PostgreSQL ; chaque élément est sauté s'il existe déjà (base PostgreSQL neuve créée
par create_all puis marquée « head »).

Revision ID: f2a7c9e1b3d4
Revises: e6f1b4c8d2a5
Create Date: 2026-11-08 20:30:00
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

from app.db import UTCDateTime

revision: str = "f2a7c9e1b3d4"
down_revision: Union[str, Sequence[str], None] = "e6f1b4c8d2a5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _in(col, values, name=None):
    return sa.CheckConstraint(f"{col} IN ({', '.join(repr(v) for v in values)})", name=name or f"ck_{col}")


def upgrade() -> None:
    insp = sa.inspect(op.get_bind())
    tables = set(insp.get_table_names())
    org = lambda: sa.Column("org_id", sa.Integer, nullable=False, server_default="1", index=True)  # noqa: E731

    if "quote_case" not in tables:
        op.create_table(
            "quote_case",
            sa.Column("id", sa.Integer, primary_key=True),
            org(),
            sa.Column("ref", sa.String(20), nullable=False, index=True),
            sa.Column("title", sa.String(200), nullable=False),
            sa.Column("branch", sa.String(40), nullable=False),
            sa.Column("stage", sa.String(12), nullable=False, server_default="new", index=True),
            sa.Column("lost_reason", sa.String(255)),
            sa.Column("company_id", sa.Integer, sa.ForeignKey("company.id", ondelete="SET NULL"), index=True),
            sa.Column("contact_id", sa.Integer, sa.ForeignKey("contact.id", ondelete="SET NULL"), index=True),
            sa.Column("client_name", sa.String(255), nullable=False),
            sa.Column("owner_id", sa.Integer, sa.ForeignKey("app_user.id", ondelete="SET NULL"), index=True),
            sa.Column("due_on", sa.Date, index=True),
            sa.Column("current_insurer", sa.String(120)),
            sa.Column("current_premium", sa.Integer),
            sa.Column("fields", sa.JSON),
            sa.Column("notes", sa.Text, nullable=False, server_default=""),
            sa.Column("created_at", UTCDateTime, nullable=False),
            sa.Column("updated_at", UTCDateTime, nullable=False),
            sa.Column("closed_at", UTCDateTime),
            _in("stage", ("new", "info", "consulting", "offers", "proposed", "won", "lost")),
        )
    if "quote_insurer" not in tables:
        op.create_table(
            "quote_insurer",
            sa.Column("id", sa.Integer, primary_key=True),
            org(),
            sa.Column("case_id", sa.Integer, sa.ForeignKey("quote_case.id", ondelete="CASCADE"), nullable=False, index=True),
            sa.Column("company_id", sa.Integer, sa.ForeignKey("company.id", ondelete="CASCADE"), nullable=False),
            sa.Column("contact_id", sa.Integer, sa.ForeignKey("contact.id", ondelete="SET NULL")),
            sa.Column("status", sa.String(10), nullable=False, server_default="to_send"),
            sa.Column("sent_at", UTCDateTime),
            sa.Column("sent_by", sa.Integer, sa.ForeignKey("app_user.id", ondelete="SET NULL")),
            sa.Column("reminders_sent", sa.Integer, nullable=False, server_default="0"),
            sa.Column("last_message_id", sa.String(255)),
            sa.Column("first_subject", sa.Text),
            sa.Column("replied_at", UTCDateTime),
            sa.Column("offer_premium", sa.Integer),
            sa.Column("notes", sa.Text, nullable=False, server_default=""),
            sa.Column("updated_at", UTCDateTime, nullable=False),
            sa.UniqueConstraint("case_id", "company_id"),
            _in("status", ("to_send", "sent", "reminded", "replied", "offer", "declined")),
        )
    if "quote_event" not in tables:
        op.create_table(
            "quote_event",
            sa.Column("id", sa.Integer, primary_key=True),
            org(),
            sa.Column("case_id", sa.Integer, sa.ForeignKey("quote_case.id", ondelete="CASCADE"), nullable=False, index=True),
            sa.Column("insurer_id", sa.Integer, sa.ForeignKey("quote_insurer.id", ondelete="SET NULL")),
            sa.Column("kind", sa.String(10), nullable=False),
            sa.Column("text", sa.Text, nullable=False),
            sa.Column("data", sa.JSON),
            sa.Column("message_id", sa.String(255), index=True),
            sa.Column("user_id", sa.Integer),
            sa.Column("ts", UTCDateTime, nullable=False, index=True),
            _in("kind", ("created", "stage", "note", "fields", "email_out", "email_in", "file", "insurer", "edit")),
        )
    if "quote_file" not in tables:
        op.create_table(
            "quote_file",
            sa.Column("id", sa.Integer, primary_key=True),
            org(),
            sa.Column("case_id", sa.Integer, sa.ForeignKey("quote_case.id", ondelete="CASCADE"), nullable=False, index=True),
            sa.Column("attachment_id", sa.Integer, sa.ForeignKey("attachment.id", ondelete="CASCADE"), nullable=False),
            sa.Column("insurer_id", sa.Integer, sa.ForeignKey("quote_insurer.id", ondelete="SET NULL")),
            sa.Column("kind", sa.String(8), nullable=False, server_default="client"),
            sa.Column("label", sa.String(120), nullable=False, server_default=""),
            sa.Column("user_id", sa.Integer),
            sa.Column("created_at", UTCDateTime, nullable=False),
            _in("kind", ("client", "offer", "other")),
        )
    cols = {c["name"] for c in insp.get_columns("reminder")}
    if "quote_case_id" not in cols:
        with op.batch_alter_table("reminder") as b:
            b.add_column(sa.Column("quote_case_id", sa.Integer, nullable=True))
            b.create_foreign_key("fk_reminder_quote_case", "quote_case", ["quote_case_id"], ["id"], ondelete="CASCADE")
            b.create_index("ix_reminder_quote_case_id", ["quote_case_id"])


def downgrade() -> None:
    with op.batch_alter_table("reminder") as b:
        b.drop_index("ix_reminder_quote_case_id")
        b.drop_constraint("fk_reminder_quote_case", type_="foreignkey")
        b.drop_column("quote_case_id")
    for t in ("quote_file", "quote_event", "quote_insurer", "quote_case"):
        op.drop_table(t)

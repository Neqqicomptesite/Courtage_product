"""pièces jointes, types de séquence, services et niveaux, logos, agenda (V2.8)

Revision ID: 7a3e9c5d2f18
Revises: 6f2d8b4c1e07
Create Date: 2026-11-04 11:00:00
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

import app.db

revision: str = "7a3e9c5d2f18"
down_revision: Union[str, Sequence[str], None] = "6f2d8b4c1e07"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Colonnes ajoutées (ALTER TABLE ADD COLUMN) : aucune table recréée, rien n'est recopié.
    # Les valeurs autorisées sont contrôlées par l'application (pas de contrainte ajoutée ici,
    # ce qui obligerait SQLite à recréer les tables contact et sequence).
    op.add_column("sequence", sa.Column("category", sa.String(length=15), server_default="prospection", nullable=False))
    op.add_column("contact", sa.Column("department", sa.String(length=20), nullable=True))
    op.add_column("contact", sa.Column("seniority", sa.String(length=12), nullable=True))
    op.add_column("company", sa.Column("logo", sa.String(length=120), nullable=True))
    op.add_column("message", sa.Column("attachments", sa.JSON(), nullable=True))
    op.create_table(
        "attachment",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("token", sa.String(length=40), nullable=False),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("content_type", sa.String(length=120), nullable=False),
        sa.Column("size", sa.Integer(), nullable=False),
        sa.Column("created_at", app.db.UTCDateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token"),
    )
    op.create_table(
        "step_attachment",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("step_id", sa.Integer(), nullable=False),
        sa.Column("attachment_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["step_id"], ["step.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["attachment_id"], ["attachment.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("step_id", "attachment_id"),
    )
    op.create_index("ix_step_attachment_step_id", "step_attachment", ["step_id"])
    op.create_table(
        "reminder",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=10), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("notes", sa.Text(), server_default="", nullable=False),
        sa.Column("due_on", sa.Date(), nullable=False),
        sa.Column("due_time", sa.String(length=5), nullable=True),
        sa.Column("contact_id", sa.Integer(), nullable=True),
        sa.Column("company_id", sa.Integer(), nullable=True),
        sa.Column("done_at", app.db.UTCDateTime(), nullable=True),
        sa.Column("created_at", app.db.UTCDateTime(), nullable=False),
        sa.CheckConstraint("kind IN ('call', 'email', 'quote', 'meeting', 'renewal', 'other')", name="ck_kind"),
        sa.ForeignKeyConstraint(["contact_id"], ["contact.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["company_id"], ["company.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_reminder_due_on", "reminder", ["due_on"])
    op.create_index("ix_reminder_contact_id", "reminder", ["contact_id"])
    op.create_index("ix_reminder_company_id", "reminder", ["company_id"])


def downgrade() -> None:
    op.drop_table("reminder")
    op.drop_table("step_attachment")
    op.drop_table("attachment")
    with op.batch_alter_table("message") as b:
        b.drop_column("attachments")
    with op.batch_alter_table("company") as b:
        b.drop_column("logo")
    with op.batch_alter_table("contact") as b:
        b.drop_column("seniority")
        b.drop_column("department")
    with op.batch_alter_table("sequence") as b:
        b.drop_column("category")

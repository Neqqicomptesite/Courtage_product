"""V3.13 : avenants rattachés aux contrats du portefeuille, et pièces jointes (contrat / avenant scanné).

SQLite ET PostgreSQL ; ajout seulement (colonne et table sautées si elles existent déjà).

Revision ID: a8d4f2b6c9e1
Revises: f1a9c3e7b5d2
Create Date: 2026-11-13 12:30:00
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

from app.db import UTCDateTime

revision: str = "a8d4f2b6c9e1"
down_revision: Union[str, Sequence[str], None] = "f1a9c3e7b5d2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    insp = sa.inspect(op.get_bind())
    have = {c["name"] for c in insp.get_columns("portfolio_contract")}
    cols = [  # pièces jointes + fiche police complète (souscription, apériteur, co-assurance, dernier sinistre)
        sa.Column("attachment_ids", sa.JSON, nullable=True),
        sa.Column("subscribed_on", sa.Date, nullable=True),
        sa.Column("aperiteur_no", sa.String(80), nullable=False, server_default=""),
        sa.Column("coinsurance", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("last_claim_on", sa.Date, nullable=True),
    ]
    missing = [c for c in cols if c.name not in have]
    if missing:
        with op.batch_alter_table("portfolio_contract") as b:
            for c in missing:
                b.add_column(c)
    if "portfolio_amendment" not in insp.get_table_names():
        op.create_table(
            "portfolio_amendment",
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column("org_id", sa.Integer, nullable=False, server_default="1"),
            sa.Column("contract_id", sa.Integer, sa.ForeignKey("portfolio_contract.id", ondelete="CASCADE"), nullable=False),
            sa.Column("number", sa.String(60), nullable=False, server_default=""),
            sa.Column("effective_on", sa.Date, nullable=True),
            sa.Column("kind", sa.String(60), nullable=False, server_default=""),
            sa.Column("description", sa.Text, nullable=False, server_default=""),
            sa.Column("premium_delta", sa.Float, nullable=True),
            sa.Column("attachment_ids", sa.JSON, nullable=True),
            sa.Column("user_id", sa.Integer, sa.ForeignKey("app_user.id", ondelete="SET NULL"), nullable=True),
            sa.Column("created_at", UTCDateTime, nullable=False),
        )
        op.create_index("ix_portfolio_amendment_org_id", "portfolio_amendment", ["org_id"])
        op.create_index("ix_portfolio_amendment_contract_id", "portfolio_amendment", ["contract_id"])


def downgrade() -> None:
    op.drop_table("portfolio_amendment")
    with op.batch_alter_table("portfolio_contract") as b:
        for name in ("attachment_ids", "subscribed_on", "aperiteur_no", "coinsurance", "last_claim_on"):
            b.drop_column(name)

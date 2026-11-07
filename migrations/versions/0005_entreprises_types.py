"""entreprises et types de contacts (V2.3)

Crée la table « company », ajoute contact.kind (prospect par défaut) et contact.company_id,
puis regroupe les contacts existants par nom d'entreprise « replié » (SANLAM Maroc = Sanlam).
Aucun regroupement approximatif : deux orthographes vraiment différentes restent deux fiches,
fusionnables ensuite depuis l'application.

Revision ID: 5e1c0a2b7d93
Revises: 2ada5cec1381
Create Date: 2026-11-04 09:00:00
"""
from collections import Counter, defaultdict
from datetime import datetime, timezone
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

import app.db

revision: str = "5e1c0a2b7d93"
down_revision: Union[str, Sequence[str], None] = "2ada5cec1381"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

KINDS = "kind IN ('prospect', 'client', 'insurer', 'partner')"


def upgrade() -> None:
    op.create_table(
        "company",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("name_key", sa.String(length=255), nullable=False),
        sa.Column("kind", sa.String(length=12), server_default="prospect", nullable=False),
        sa.Column("domain", sa.String(length=255), nullable=True),
        sa.Column("website", sa.String(length=255), nullable=True),
        sa.Column("phone", sa.String(length=60), nullable=True),
        sa.Column("sector", sa.String(length=255), nullable=True),
        sa.Column("notes", sa.Text(), server_default="", nullable=False),
        sa.Column("created_at", app.db.UTCDateTime(), nullable=False),
        sa.Column("updated_at", app.db.UTCDateTime(), nullable=False),
        sa.CheckConstraint(KINDS, name="ck_kind"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name_key"),
    )
    with op.batch_alter_table("company") as b:
        b.create_index("ix_company_kind", ["kind"])
        b.create_index("ix_company_domain", ["domain"])
    with op.batch_alter_table("contact") as b:
        b.add_column(sa.Column("kind", sa.String(length=12), server_default="prospect", nullable=False))
        b.add_column(sa.Column("company_id", sa.Integer(), nullable=True))
        b.create_foreign_key("fk_contact_company_id_company", "company", ["company_id"], ["id"], ondelete="SET NULL")
        b.create_check_constraint("ck_kind", KINDS)
        b.create_index("ix_contact_kind", ["kind"])
        b.create_index("ix_contact_company_id", ["company_id"])

    # --- reprise des données : une fiche par nom d'entreprise replié
    from app.companies_service import best_name, company_key, email_domain  # règles figées au 04/11/2026
    bind = op.get_bind()
    groups: dict[str, list] = defaultdict(list)
    for cid, email, company in bind.execute(sa.text("SELECT id, email, company FROM contact WHERE trim(coalesce(company, '')) != ''")):
        groups[company_key(company)].append((cid, email, company))
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S.%f")
    for key, rows in groups.items():
        if not key:
            continue
        name = best_name([r[2] for r in rows])
        domains = Counter(d for d in (email_domain(r[1]) for r in rows) if d)
        domain = domains.most_common(1)[0][0] if domains else None
        bind.execute(sa.text(
            "INSERT INTO company (name, name_key, kind, domain, notes, created_at, updated_at) "
            "VALUES (:n, :k, 'prospect', :d, '', :t, :t)"), {"n": name, "k": key, "d": domain, "t": now})
        new_id = bind.execute(sa.text("SELECT id FROM company WHERE name_key = :k"), {"k": key}).scalar_one()
        for cid, _, _ in rows:
            bind.execute(sa.text("UPDATE contact SET company_id = :c, company = :n WHERE id = :i"), {"c": new_id, "n": name, "i": cid})


def downgrade() -> None:
    with op.batch_alter_table("contact") as b:
        b.drop_index("ix_contact_company_id")
        b.drop_index("ix_contact_kind")
        b.drop_constraint("ck_kind", type_="check")
        b.drop_constraint("fk_contact_company_id_company", type_="foreignkey")
        b.drop_column("company_id")
        b.drop_column("kind")
    op.drop_table("company")

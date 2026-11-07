"""envoyer seulement les premiers emails d'une séquence (V2.24)

Enrollment.max_steps : nombre d'emails à envoyer pour cette inscription (NULL = toute la
séquence). Exemple : la demande d'avenant G1 envoyée « 1er email seulement » depuis la boîte
mail : pas de relance automatique. Colonne ajoutée seulement si elle manque (relance possible).

Revision ID: a3e8d1c5f7b2
Revises: 9c5e2a7b4d10
Create Date: 2026-11-06 13:00:00
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a3e8d1c5f7b2"
down_revision: Union[str, Sequence[str], None] = "9c5e2a7b4d10"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    if conn.dialect.name != "sqlite":
        return  # V3 : les bases PostgreSQL sont créées directement à jour
    cols = {r[1] for r in conn.exec_driver_sql("PRAGMA table_info(enrollment)")}
    if "max_steps" not in cols:
        op.add_column("enrollment", sa.Column("max_steps", sa.Integer(), nullable=True))


def downgrade() -> None:
    pass  # colonne facultative : la laisser ne gêne aucune version précédente

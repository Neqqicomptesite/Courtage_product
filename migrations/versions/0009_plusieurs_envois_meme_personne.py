"""une même séquence de gestion ou de souscription peut partir plusieurs fois à la même personne (V2.23)

Avant : une seule inscription par (campagne, contact). Les envois « à l'unité » d'une séquence
partageant une même campagne (« À l'unité – G1 »), un gestionnaire ne pouvait recevoir G1 qu'une
seule fois dans toute la vie de l'application, alors qu'il reçoit une demande d'avenant par dossier.

SQLite ne sait pas retirer une contrainte : la table est recréée à l'identique sans elle (procédure
officielle de SQLite : nouvelle table, copie, suppression, renommage), dans la transaction de la
migration. Les clés étrangères doivent être INACTIVES pendant l'opération (c'est le cas sur la
connexion d'Alembic) ; sinon la migration s'arrête sans rien toucher. Les lignes et les liens des
messages vers les inscriptions sont comptés avant et après.

Revision ID: 9c5e2a7b4d10
Revises: 8b4f1d6e3a29
Create Date: 2026-11-04 20:30:00
"""
import re
from typing import Sequence, Union

from alembic import op

revision: str = "9c5e2a7b4d10"
down_revision: Union[str, Sequence[str], None] = "8b4f1d6e3a29"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

UNIQUE_RE = re.compile(r",\s*UNIQUE\s*\(\s*campaign_id\s*,\s*contact_id\s*\)", re.I)


def upgrade() -> None:
    conn = op.get_bind()
    if conn.dialect.name != "sqlite":
        return  # V3 : les bases PostgreSQL sont créées directement à jour
    if conn.exec_driver_sql("PRAGMA foreign_keys").scalar():
        raise RuntimeError("Clés étrangères actives : migration 0009 arrêtée sans rien modifier.")
    ddl = conn.exec_driver_sql("SELECT sql FROM sqlite_master WHERE type='table' AND name='enrollment'").scalar()
    if not ddl or not UNIQUE_RE.search(ddl):
        return  # déjà fait (ou base créée sans la contrainte)
    new_ddl = UNIQUE_RE.sub("", ddl).replace("CREATE TABLE enrollment", "CREATE TABLE enrollment_new", 1)
    cols = ", ".join(r[1] for r in conn.exec_driver_sql("PRAGMA table_info(enrollment)"))
    n_before = conn.exec_driver_sql("SELECT count(*) FROM enrollment").scalar()
    links_before = conn.exec_driver_sql("SELECT count(*) FROM message WHERE enrollment_id IS NOT NULL").scalar()

    conn.exec_driver_sql("DROP TABLE IF EXISTS enrollment_new")
    conn.exec_driver_sql(new_ddl)
    conn.exec_driver_sql(f"INSERT INTO enrollment_new ({cols}) SELECT {cols} FROM enrollment")
    conn.exec_driver_sql("DROP TABLE enrollment")
    conn.exec_driver_sql("ALTER TABLE enrollment_new RENAME TO enrollment")
    conn.exec_driver_sql("CREATE INDEX IF NOT EXISTS ix_enrollment_next_due_at ON enrollment (next_due_at)")
    conn.exec_driver_sql("CREATE INDEX IF NOT EXISTS ix_enrollment_status ON enrollment (status)")
    conn.exec_driver_sql("CREATE INDEX IF NOT EXISTS ix_enrollment_campaign_contact ON enrollment (campaign_id, contact_id)")

    n_after = conn.exec_driver_sql("SELECT count(*) FROM enrollment").scalar()
    links_after = conn.exec_driver_sql("SELECT count(*) FROM message WHERE enrollment_id IS NOT NULL").scalar()
    if (n_before, links_before) != (n_after, links_after):
        raise RuntimeError(f"Migration 0009 : comptes différents {(n_before, links_before)} -> {(n_after, links_after)}")


def downgrade() -> None:
    pass  # remettre la contrainte échouerait dès qu'une personne a reçu deux fois la même séquence

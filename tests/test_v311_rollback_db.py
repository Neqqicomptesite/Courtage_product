"""V3.11 : après un retour automatique à la version d'avant, la base porte une révision plus récente
que le code. L'ancienne version doit démarrer quand même (migrations « ajout seulement »)."""
from sqlalchemy import text

from app import migrate
from app.db import get_session


def test_old_code_starts_on_a_newer_database(db):
    with get_session() as s:
        before = s.execute(text("SELECT version_num FROM alembic_version")).scalar()
        s.execute(text("UPDATE alembic_version SET version_num = 'f0f0f0f0f0f0'"))  # révision d'une version future
        s.commit()
    try:
        migrate.upgrade_to_head()  # ne doit pas lever « Can't locate revision »
        with get_session() as s:
            assert s.execute(text("SELECT version_num FROM alembic_version")).scalar() == "f0f0f0f0f0f0"
    finally:
        with get_session() as s:
            s.execute(text("UPDATE alembic_version SET version_num = :v"), {"v": before})
            s.commit()
    migrate.upgrade_to_head()  # révision connue : rien à faire, pas d'erreur

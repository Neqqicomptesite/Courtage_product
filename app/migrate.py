"""Applique les migrations Alembic (appelé par le lanceur et par les tests)."""
from alembic import command
from alembic.config import Config

from app.paths import PROJECT_DIR, database_url


def upgrade_to_head() -> None:
    cfg = Config(str(PROJECT_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(PROJECT_DIR / "migrations"))
    url = database_url()
    if url.startswith("postgresql"):
        # V3 : une base PostgreSQL neuve est créée d'un coup à partir des modèles, puis
        # marquée « à jour ». L'historique des migrations SQLite (0001 à 0010) ne s'y applique
        # pas ; les migrations suivantes, elles, doivent marcher sur les deux bases.
        from sqlalchemy import create_engine, inspect

        from app import models  # noqa: F401
        from app.db import Base
        engine = create_engine(url)
        try:
            if "alembic_version" not in inspect(engine).get_table_names():
                Base.metadata.create_all(engine)
                cfg.attributes["db_url"] = url
                command.stamp(cfg, "head")
            else:
                cfg.attributes["db_url"] = url
                command.upgrade(cfg, "head")
            # V3 : tables fermées à l'API publique de Supabase, à chaque démarrage (app/db_lockdown.py)
            from app.db_lockdown import lock_down
            with engine.begin() as conn:
                lock_down(conn)
        finally:
            engine.dispose()
        return
    command.upgrade(cfg, "head")

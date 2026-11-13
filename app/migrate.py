"""Applique les migrations Alembic (appelé par le lanceur et par les tests)."""
from alembic import command
from alembic.config import Config

from app.paths import PROJECT_DIR, database_url


def _ahead_of_code(cfg: Config, url: str | None) -> str | None:
    """V3.11 : la base porte une révision que ce code ne connaît pas (elle a été mise à jour par une
    version plus récente, puis la mise à jour a été annulée : retour automatique). Les migrations ne
    font qu'ajouter des tables et des colonnes : l'ancienne version tourne sur la base plus récente.
    On ne touche donc à rien (Alembic refuserait de démarrer). Renvoie la révision inconnue, ou None."""
    from alembic.runtime.migration import MigrationContext
    from alembic.script import ScriptDirectory
    from sqlalchemy import create_engine
    engine = create_engine(url or database_url())
    try:
        with engine.connect() as conn:
            heads = MigrationContext.configure(conn).get_current_heads()
    except Exception:  # noqa: BLE001 (base neuve ou illisible : Alembic dira quoi)
        return None
    finally:
        engine.dispose()
    script = ScriptDirectory.from_config(cfg)
    for rev in heads:
        try:
            script.get_revision(rev)
        except Exception:  # noqa: BLE001
            return rev
    return None


def _upgrade(cfg: Config, url: str | None = None) -> None:
    unknown = _ahead_of_code(cfg, url)
    if unknown:
        import logging
        logging.getLogger("oddo").warning(
            "Base en avance sur le code (révision %s inconnue) : retour à une version précédente, "
            "migrations sautées (elles n'ont fait qu'ajouter).", unknown)
        return
    command.upgrade(cfg, "head")


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
                _upgrade(cfg, url)
            # V3 : tables fermées à l'API publique de Supabase, à chaque démarrage (app/db_lockdown.py)
            from app.db_lockdown import lock_down
            with engine.begin() as conn:
                lock_down(conn)
        finally:
            engine.dispose()
        return
    _upgrade(cfg)

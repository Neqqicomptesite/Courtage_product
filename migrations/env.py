"""Configuration Alembic.

L'URL de la base n'est pas écrite dans alembic.ini : on la calcule depuis
app.paths (qui respecte ODDO_DATA_DIR pour les tests).

render_as_batch=True est indispensable avec SQLite : SQLite ne sait pas
modifier une colonne existante (ALTER COLUMN). Alembic contourne en recréant
la table (« batch mode »). Sans ça, la plupart des migrations futures échoueraient.
"""
from alembic import context
from sqlalchemy import create_engine

from app import models  # noqa: F401  (enregistre toutes les tables dans Base.metadata)
from app.db import Base
from app.paths import database_url, ensure_dirs

target_metadata = Base.metadata


def _url() -> str:
    override = context.config.attributes.get("db_url")
    if override:
        return override
    ensure_dirs()
    return database_url()


def run_migrations_offline() -> None:
    context.configure(url=_url(), target_metadata=target_metadata,
                      literal_binds=True, render_as_batch=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = create_engine(_url())
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata,
                          render_as_batch=connection.dialect.name == "sqlite")
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()

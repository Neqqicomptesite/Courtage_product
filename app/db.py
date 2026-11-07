"""Connexion SQLite et type de date UTC.

Concept clé : SQLite n'a pas de vrai type « date avec fuseau ». Si on lui donne
un datetime avec fuseau, SQLAlchemy l'écrit sous forme de texte et le relit
SANS fuseau. UTCDateTime corrige ça : il refuse les dates sans fuseau à
l'écriture (pour attraper les bugs tôt) et remet le fuseau UTC à la lecture.
"""
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import DateTime, Engine, create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.types import TypeDecorator


class UTCDateTime(TypeDecorator):
    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect):
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("Date sans fuseau refusée : utilisez app.timeutil.utcnow()")
        return value.astimezone(timezone.utc).replace(tzinfo=None)

    def process_result_value(self, value: datetime | None, dialect):
        if value is None:
            return None
        return value.replace(tzinfo=timezone.utc)


class Base(DeclarativeBase):
    pass


def make_engine(target: "Path | str") -> Engine:
    url = target if isinstance(target, str) else f"sqlite:///{target}"
    if url.startswith("postgresql"):
        # V3 : serveur (Supabase). pool_pre_ping : reconnecte après une coupure réseau.
        return create_engine(url, pool_pre_ping=True, pool_size=5, max_overflow=5, pool_recycle=1800)
    # check_same_thread=False : le serveur web et le planificateur tournent dans
    # des threads différents et partagent la même base.
    engine = create_engine(url, connect_args={"check_same_thread": False})

    @event.listens_for(engine, "connect")
    def _sqlite_pragmas(dbapi_conn, _record):
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")   # lectures pendant les écritures
        cur.execute("PRAGMA foreign_keys=ON")    # SQLite les ignore sinon !
        cur.execute("PRAGMA busy_timeout=5000")  # attend 5 s au lieu d'échouer si la base est occupée
        cur.close()

    return engine


_engine: Engine | None = None
SessionLocal = sessionmaker(expire_on_commit=False)


def _install_scope() -> None:
    from app import scope  # V3 : filtre « chaque employé ses données » (sans effet en poste unique)
    scope.install(SessionLocal)


def init_engine(target: "Path | str | None" = None) -> Engine:
    """Appelé une fois au démarrage (ou par chaque test avec sa propre base).
    Sans argument : DATABASE_URL (serveur) ou la base SQLite locale."""
    from app.paths import database_url
    global _engine
    if _engine is not None:
        _engine.dispose()
    _engine = make_engine(target if target is not None else database_url())
    if not getattr(SessionLocal, "_oddo_scoped", False):
        _install_scope()
        SessionLocal._oddo_scoped = True
    from app import scope
    scope.forget_cache()
    SessionLocal.configure(bind=_engine)
    return _engine


def get_engine() -> Engine:
    if _engine is None:
        raise RuntimeError("init_engine() n'a pas été appelé")
    return _engine


def get_session() -> Session:
    return SessionLocal()

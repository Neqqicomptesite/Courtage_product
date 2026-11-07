"""Fixtures partagées : base temporaire, coffre de mots de passe en mémoire, faux serveurs.

Les tests se connectent aux faux serveurs par « 127.0.0.1 » et jamais par « localhost » :
sous Windows, « localhost » essaie d'abord l'adresse IPv6 ::1, où rien n'écoute, et Windows
attend environ 2 secondes avant d'abandonner, à chaque connexion (tests 30 fois plus lents).

Chaque test tourne dans un dossier data/ temporaire : la vraie base n'est jamais touchée.
"""
import os
import keyring
import pytest
from fastapi.testclient import TestClient
from keyring.backend import KeyringBackend
from keyring.errors import PasswordDeleteError

from app.mail import transport
from tests.fakes.certs import CA_FILE
from tests.fakes.fake_imap import FakeImapServer
from tests.fakes.fake_smtp import FakeSmtpServer

USER = "o.douiri@oddo.ma"
PASSWORD = "Mot-de-passe-de-test-42"


class MemoryKeyring(KeyringBackend):
    """Remplace le Gestionnaire d'identification Windows pendant les tests."""
    priority = 1

    def __init__(self):
        super().__init__()
        self.store: dict[tuple[str, str], str] = {}

    def set_password(self, service, username, password):
        self.store[(service, username)] = password

    def get_password(self, service, username):
        return self.store.get((service, username))

    def delete_password(self, service, username):
        if (service, username) not in self.store:
            raise PasswordDeleteError("absent")
        del self.store[(service, username)]


@pytest.fixture(autouse=True)
def isolated_env(tmp_path, monkeypatch):
    monkeypatch.setenv("ODDO_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("ODDO_EXTRA_CA_FILE", str(CA_FILE))
    monkeypatch.setattr(transport, "TIMEOUT_S", 5)
    # Les tests d'avant la V2.12 vérifient la ligne STOP : on la garde active pour eux.
    from app import settings_store
    monkeypatch.setattr(settings_store, "UNSUBSCRIBE_DEFAULT", True)
    kr = MemoryKeyring()
    keyring.set_keyring(kr)
    yield kr


@pytest.fixture
def memory_keyring(isolated_env):
    return isolated_env


PG_TEST_URL = os.environ.get("TEST_DATABASE_URL", "")  # V3 : lancer les tests sur PostgreSQL


@pytest.fixture
def db(tmp_path, monkeypatch):
    """Base migrée par Alembic (comme en vrai) + moteur SQLAlchemy prêt.
    V3 : avec TEST_DATABASE_URL, chaque test part d'une base PostgreSQL vide."""
    from app.db import init_engine
    from app.migrate import upgrade_to_head
    from app.paths import database_url, ensure_dirs

    ensure_dirs()
    if PG_TEST_URL:
        monkeypatch.setenv("DATABASE_URL", PG_TEST_URL)
        from cryptography.fernet import Fernet
        monkeypatch.setenv("ODDO_SECRET_KEY", Fernet.generate_key().decode())  # coffre du serveur
        from sqlalchemy import create_engine, text
        eng = create_engine(database_url())
        with eng.begin() as c:
            c.execute(text("DROP SCHEMA public CASCADE")); c.execute(text("CREATE SCHEMA public"))
        eng.dispose()
    upgrade_to_head()
    engine = init_engine()
    yield engine
    engine.dispose()


@pytest.fixture
def client(db, monkeypatch):
    from app.web import app as appmod
    from app.web.app import create_app
    if PG_TEST_URL:
        # tests « poste unique » rejoués sur PostgreSQL : sans connexion Supabase
        # (la connexion obligatoire a ses propres tests, test_v3_auth.py)
        monkeypatch.setattr(appmod, "is_server_mode", lambda: False)

    with TestClient(create_app(testing=True)) as c:
        yield c


@pytest.fixture(params=["ssl", "starttls"])
def smtp_server(request):
    server = FakeSmtpServer(USER, PASSWORD, mode=request.param).start()
    yield server
    server.stop()


@pytest.fixture
def smtp_ssl():
    server = FakeSmtpServer(USER, PASSWORD, mode="ssl").start()
    yield server
    server.stop()


@pytest.fixture
def imap_server():
    server = FakeImapServer(USER, PASSWORD).start()
    yield server
    server.stop()


def pytest_collection_modifyitems(config, items):
    """V3 : les tests propres à SQLite (sauvegarde par copie de fichier, restauration,
    anciennes migrations) ne concernent pas PostgreSQL."""
    if not PG_TEST_URL:
        return
    skip = pytest.mark.skip(reason="propre à la base SQLite locale")
    for it in items:
        if "sqlite_only" in it.keywords:
            it.add_marker(skip)

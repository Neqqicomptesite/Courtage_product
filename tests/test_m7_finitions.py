"""M7 : restauration de sauvegarde, page Journal, fichiers de lancement Windows."""
import sqlite3
from pathlib import Path

import pytest
from sqlalchemy import select

from app import restore
from app.backup import KEEP, backup_now
from app.db import get_session, init_engine
from app.launcher import InstanceLock
from app.models import Contact, EventLog
from app.paths import PROJECT_DIR, backups_dir, data_dir, db_path

ORIGIN = {"Origin": "http://testserver"}


def _contacts():
    with get_session() as s:
        return sorted(c.email for c in s.scalars(select(Contact)))


@pytest.mark.sqlite_only
def test_restore_brings_back_old_state_and_keeps_safety_copy(db):
    with get_session() as s:
        s.add(Contact(email="avant@exemple.ma"))
        s.commit()
    old = backup_now("test")
    with get_session() as s:
        s.add(Contact(email="apres@exemple.ma"))
        s.commit()
    db.dispose()  # l'application est « fermée »
    safety = restore.restore(old)
    init_engine(db_path())
    assert _contacts() == ["avant@exemple.ma"]
    # la copie de sécurité contient l'état d'avant la restauration
    c = sqlite3.connect(safety)
    assert sorted(r[0] for r in c.execute("select email from contact")) == ["apres@exemple.ma", "avant@exemple.ma"]
    c.close()


def test_restore_refused_while_app_is_open(db):
    path = backup_now("test")
    lock = InstanceLock(data_dir() / "app.lock")
    assert lock.acquire()
    try:
        with pytest.raises(restore.RestoreRefused, match="fermez-la"):
            restore.restore(path)
    finally:
        lock.release()


def test_restore_refuses_damaged_backup(db, tmp_path):
    bad = backups_dir() / "oddo_2026-01-01_000000_abime.db"
    bad.write_bytes(b"ceci n'est pas une base sqlite" * 100)
    with pytest.raises(restore.RestoreRefused, match="endommagée"):
        restore.restore(bad)


@pytest.mark.sqlite_only
def test_restore_oldest_backup_even_when_pruning(db):
    for i in range(KEEP):
        backup_now(f"b{i}")
    oldest = restore.list_backups()[-1]
    restore.restore(oldest)  # la copie de sécurité va supprimer « oldest » : ne doit pas planter
    assert len(restore.list_backups()) == KEEP


def test_journal_page_lists_and_filters(client):
    with get_session() as s:
        s.add(EventLog(level="info", entity="campaign", entity_id=1, text="Campagne « Test » activée"))
        s.add(EventLog(level="error", entity="engine", text="Envoi suspendu : mot de passe refusé"))
        s.commit()
    page = client.get("/journal").text
    assert "Campagne « Test » activée" in page and "mot de passe refusé" in page
    errors = client.get("/journal?level=error").text
    assert "mot de passe refusé" in errors and "Campagne « Test » activée" not in errors
    assert "Campagne « Test »" in client.get("/journal?q=campagne").text
    assert "Campagne « Test »" not in client.get("/journal?entity=engine").text


@pytest.mark.parametrize("name", ["start.bat", "restaurer_sauvegarde.bat", "lancer_tests.bat"])
def test_windows_batch_files_have_crlf_and_ascii(name):
    raw = (PROJECT_DIR / name).read_bytes()
    raw.decode("ascii")  # cmd.exe affiche mal les accents : fichiers en ASCII pur
    assert b"\r\n" in raw and b"\n" not in raw.replace(b"\r\n", b"")


def test_requirements_pin_direct_dependencies():
    req = (PROJECT_DIR / "requirements.txt").read_text(encoding="utf-8")
    for pkg in ("fastapi==", "uvicorn==", "SQLAlchemy==", "alembic==", "APScheduler==", "openpyxl==", "keyring=="):
        assert pkg in req
    assert "tzdata>=" in req  # jamais figé : les règles d'heure changent


def test_every_page_renders(client):
    for url in ["/classique", "/contacts", "/contacts/import", "/contacts/exclusions", "/sequences", "/sequences/blocks",
                "/sequences/1", "/sequences/1/preview", "/campaigns", "/replies", "/journal", "/settings",
                "/aide/delivrabilite"]:
        r = client.get(url)
        assert r.status_code == 200, url
        assert "Internal Server Error" not in r.text

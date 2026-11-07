import pytest
"""V2.24 : n'envoyer qu'une partie de la séquence (« 1er email seulement », « 1er email +
relance 1 ») à l'unité, depuis la boîte mail ou une fiche."""
import sqlite3
from datetime import timedelta

from sqlalchemy import select

from app.db import get_session
from app.models import Enrollment
from app.paths import db_path
from tests.test_m4_engine import world  # noqa: F401
from tests.test_v223 import OV, ORIGIN, _setup


def _run_days(days=20):
    from app import engine
    from app.scheduling import SendWindow
    with get_session() as s:
        now = SendWindow.from_settings(s).next_open(max(e.next_due_at for e in s.scalars(select(Enrollment))) + timedelta(minutes=1))
    end = now + timedelta(days=days)
    sent = 0
    while now < end:
        r = engine.tick(now=now, sync=False)
        sent += r.action == "sent"
        now += timedelta(hours=3)
    return sent


def _send(client, sid, cid, **extra):
    r = client.post(f"/api/sequences/{sid}/send", json={"contact_ids": [cid], "overrides": OV, **extra}, headers=ORIGIN).json()
    assert r["sent"] and not r["refused"], r
    return r


def test_first_email_only(client, world):  # noqa: F811
    g, _, seq = _setup()
    _send(client, seq["G1"], g, max_steps=1)
    assert _run_days() == 1
    with get_session() as s:
        e = s.scalars(select(Enrollment)).one()
        assert e.max_steps == 1 and e.status == "completed"
    assert len(world["smtp"].messages) == 1


def test_first_two_emails(client, world):  # noqa: F811
    g, _, seq = _setup()
    _send(client, seq["G1"], g, max_steps=2)
    assert _run_days() == 2
    with get_session() as s:
        assert s.scalars(select(Enrollment)).one().status == "completed"


def test_whole_sequence_by_default(client, world):  # noqa: F811
    g, _, seq = _setup()
    _send(client, seq["G1"], g)
    with get_session() as s:
        e = s.scalars(select(Enrollment)).one()
        assert e.max_steps is None
    assert _run_days() == 3


def test_max_steps_not_below_sequence_length(client, world):  # noqa: F811
    """Demander 3 emails sur une séquence de 3 = toute la séquence (pas de limite stockée)."""
    g, _, seq = _setup()
    _send(client, seq["G1"], g, max_steps=3)
    with get_session() as s:
        assert s.scalars(select(Enrollment)).one().max_steps is None


def test_holes_only_for_sent_emails(client, world):  # noqa: F811
    _, _, seq = _setup()
    every = client.get(f"/api/sequences/{seq['G1']}/holes").json()["holes"]
    first = client.get(f"/api/sequences/{seq['G1']}/holes?steps=1").json()["holes"]
    assert set(first) <= set(every) and first


def test_unfinished_relance_does_not_block_first_email_only(client, world):  # noqa: F811
    """Une relance avec un [champ] non rempli bloque l'envoi complet, pas « 1er email seulement »."""
    from app.models import Sequence, Step
    g, _, seq = _setup()
    with get_session() as s:
        st = s.scalars(select(Step).where(Step.sequence_id == seq["G1"], Step.position == 2)).one()
        st.body_template += "\n[Pièce manquante]"
        s.commit()
    r = client.post(f"/api/sequences/{seq['G1']}/send", json={"contact_ids": [g], "overrides": OV}, headers=ORIGIN).json()
    assert not r["sent"] and r["refused"][0]["problems"], r
    r = client.post(f"/api/sequences/{seq['G1']}/send", json={"contact_ids": [g], "overrides": OV, "max_steps": 1}, headers=ORIGIN).json()
    assert r["sent"] and not r["refused"], r


def test_enrollment_json_has_max_steps(client, world):  # noqa: F811
    g, _, seq = _setup()
    r = _send(client, seq["G1"], g, max_steps=1)
    camp = client.get(f"/api/campaigns/{r['campaign']['id']}").json()
    assert [e["max_steps"] for e in camp["enrollments"]] == [1]


@pytest.mark.sqlite_only
def test_migration_adds_column(db):
    con = sqlite3.connect(db_path())
    cols = {r[1] for r in con.execute("PRAGMA table_info(enrollment)")}
    con.close()
    assert "max_steps" in cols

"""M1 : schéma, seed, réglages par défaut, dates UTC."""
from datetime import datetime, timezone

import pytest
from sqlalchemy import inspect, select

from app import settings_store
from app.db import get_session
from app.models import ContentBlock, EventLog, Sequence, Step, StepVariant
from app.seed import run_seed

EXPECTED_TABLES = {"mailbox", "contact", "suppression", "content_block", "sequence", "step",
                   "step_variant", "campaign", "enrollment", "message", "imap_state",
                   "event_log", "setting", "alembic_version"}


def test_migration_creates_all_tables(db):
    assert EXPECTED_TABLES <= set(inspect(db).get_table_names())


def test_seed_creates_content_once(db):
    with get_session() as s, s.begin():
        assert run_seed(s) is True
    with get_session() as s, s.begin():
        assert run_seed(s) is False  # deuxième appel : rien de recréé
    with get_session() as s:
        keys = {(b.kind, b.key) for b in s.scalars(select(ContentBlock))}
        assert len(keys) == 10
        assert ("target", "FIN") in keys and ("sector", "SANTE") in keys
        assert all("À RÉDIGER" in b.body for b in s.scalars(select(ContentBlock)))
        seq = s.scalars(select(Sequence)).one()
        steps = s.scalars(select(Step).where(Step.sequence_id == seq.id).order_by(Step.position)).all()
        assert [st.position for st in steps] == [1, 2, 3]
        assert "{{ bloc_cible }}" in steps[0].body_template
        assert "{{ bloc_secteur }}" in steps[0].body_template
        assert [st.same_thread for st in steps] == [False, True, True]
        # J0, J+3, J+7 ouvrés -> délais depuis l'étape précédente : 0, 3, 4
        assert [st.delay_days for st in steps] == [0, 3, 4]
        labels = sorted(v.label for v in s.scalars(select(StepVariant)))
        assert labels == ["A", "B"]


def test_test_mode_is_on_by_default(db):
    with get_session() as s:
        assert settings_store.get(s, "test_mode") is True
        assert settings_store.get(s, "send_windows") == [["09:00", "12:30"], ["14:30", "17:30"]]
        assert "STOP" in settings_store.get(s, "unsubscribe_line")


def test_unknown_setting_is_rejected(db):
    with get_session() as s, pytest.raises(KeyError):
        settings_store.get(s, "faute_de_frappe")


def test_holidays_prefilled_include_unity_day(db):
    with get_session() as s:
        hol = settings_store.get(s, "holidays")
    dates = {h["date"] for h in hol}
    assert "2026-10-31" in dates or "2027-10-31" in dates
    assert any("(estimé)" in h["label"] for h in hol if h["date"].startswith("2027"))


def test_utc_datetime_roundtrip_and_naive_rejected(db):
    aware = datetime(2026, 11, 3, 9, 30, tzinfo=timezone.utc)
    with get_session() as s, s.begin():
        s.add(EventLog(text="essai", ts=aware))
    with get_session() as s:
        row = s.scalars(select(EventLog)).one()
        assert row.ts == aware and row.ts.tzinfo is not None
    with get_session() as s:
        s.add(EventLog(text="naïf", ts=datetime(2026, 11, 3, 9, 30)))
        with pytest.raises(Exception, match="sans fuseau"):
            s.flush()


def test_status_check_constraint(db):
    from app.models import Contact
    with get_session() as s:
        s.add(Contact(email="x@y.ma", global_status="actif"))  # faute volontaire
        with pytest.raises(Exception, match="(?i)check"):
            s.flush()

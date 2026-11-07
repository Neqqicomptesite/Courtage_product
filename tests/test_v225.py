"""V2.25 : « Vérifier avant d'envoyer » (les emails exacts, rien n'est enregistré) et
« Envoyés sans réponse » (après la DERNIÈRE relance seulement)."""
from datetime import timedelta

from sqlalchemy import func, select

from app import stats
from app.db import get_session
from app.models import EventLog, Campaign, Contact, Enrollment
from app.scheduling import SendWindow
from tests.test_m4_engine import world  # noqa: F401
from tests.test_v223 import OV, ORIGIN, _setup
from tests.test_v224 import _run_days


def _counts():
    with get_session() as s:
        return (s.scalar(select(func.count(Enrollment.id))), s.scalar(select(func.count(Campaign.id))),
                s.scalar(select(func.count(EventLog.id))))


def test_review_single_exact_and_nothing_saved(client, world):  # noqa: F811
    g, _, seq = _setup()
    before = _counts()
    r = client.post(f"/api/sequences/{seq['G1']}/review", json={"contact_ids": [g], "overrides": OV}, headers=ORIGIN)
    assert r.status_code == 200, r.text
    d = r.json()
    assert _counts() == before  # joué « à blanc »
    p = d["people"][0]
    assert not p["refused"] and len(p["emails"]) == 3 and d["total_steps"] == 3
    first = p["emails"][0]
    assert "40.1" in first["subject"] and first["planned_at"] and not first["problems"]
    assert p["emails"][1]["subject"].startswith("Re:")
    assert all(e["planned_at"] for e in p["emails"])
    assert p["emails"][0]["planned_at"] < p["emails"][1]["planned_at"] < p["emails"][2]["planned_at"]


def test_review_matches_what_is_sent(client, world):  # noqa: F811
    """L'objet et le texte montrés sont ceux qui partent (même calcul que le moteur)."""
    g, _, seq = _setup()
    d = client.post(f"/api/sequences/{seq['G1']}/review", json={"contact_ids": [g], "overrides": OV, "max_steps": 1}, headers=ORIGIN).json()
    shown = d["people"][0]["emails"]
    assert len(shown) == 1
    client.post(f"/api/sequences/{seq['G1']}/send", json={"contact_ids": [g], "overrides": OV, "max_steps": 1}, headers=ORIGIN)
    _run_days(3)
    msg = world["smtp"].messages[0]
    raw = msg.as_string() if hasattr(msg, "as_string") else str(msg)
    assert shown[0]["body"].splitlines()[0] in raw.replace("=\n", "") or shown[0]["body"].splitlines()[0] in str(msg)


def test_review_several_people_fills_and_refusals(client, world):  # noqa: F811
    g, _, seq = _setup()
    with get_session() as s:
        h = Contact(email="souscription@autre.ma", first_name="Samir", kind="insurer", company="Autre")
        s.add(h); s.commit(); h = h.id
    holes = client.get(f"/api/sequences/{seq['S1']}/holes").json()["holes"]
    # sans les champs : refusés, avec la raison
    d = client.post(f"/api/sequences/{seq['S1']}/review", json={"contact_ids": [g, h]}, headers=ORIGIN).json()
    assert all(p["refused"] and p["problems"] for p in d["people"])
    fills = {k: f"valeur {i}" for i, k in enumerate(holes)}
    d = client.post(f"/api/sequences/{seq['S1']}/review", json={"contact_ids": [g, h], "fills": fills}, headers=ORIGIN).json()
    assert [p["refused"] for p in d["people"]] == [None, None]
    for p in d["people"]:
        assert all("[" + k + "]" not in e["body"] for e in p["emails"] for k in holes)
        assert "valeur 0" in p["emails"][0]["body"] + p["emails"][0]["subject"]
    assert d["people"][0]["emails"][0]["body"].startswith("Bonjour Karima")
    assert d["people"][1]["emails"][0]["body"].startswith("Bonjour Samir")


def test_first_due_is_next_opening_not_click_time(client, world):  # noqa: F811
    g, _, seq = _setup()
    r = client.post(f"/api/sequences/{seq['G1']}/send", json={"contact_ids": [g], "overrides": OV}, headers=ORIGIN).json()
    with get_session() as s:
        e = s.scalars(select(Enrollment)).one()
        w = SendWindow.from_settings(s)
        assert w.next_open(e.next_due_at) == e.next_due_at  # dans une plage d'envoi


def test_followup_even_while_relances_pending(client, world):  # noqa: F811
    """V2.25.1 (choix d'Omar) : listée N jours ouvrés après l'email, même si une relance est prévue."""
    g, _, seq = _setup()
    client.post(f"/api/sequences/{seq['G1']}/send", json={"contact_ids": [g], "overrides": OV}, headers=ORIGIN)
    from app import engine
    with get_session() as s:
        w = SendWindow.from_settings(s)
        now = w.next_open(s.scalars(select(Enrollment)).one().next_due_at)
    engine.tick(now=now, sync=False)  # 1er email parti, relances prévues
    with get_session() as s:
        assert g not in [r["contact"].id for r in stats.followups(s, now + timedelta(hours=2), w, 3)]
        rows = [r for r in stats.followups(s, now + timedelta(days=6), w, 3) if r["contact"].id == g]
        assert rows and rows[0]["next"] is not None  # la relance prévue est jointe à la ligne
        assert rows[0]["next"].current_step == 2 and rows[0]["next_campaign"] is not None


def test_followup_old_reply_does_not_hide_new_silence(client, world):  # noqa: F811
    """Un assureur qui a répondu à l'échange d'avant, puis plus rien sur le nouveau : listé."""
    from app.models import Message
    from app.timeutil import utcnow
    g, _, seq = _setup()
    now = utcnow()
    with get_session() as s:
        s.add(Message(contact_id=g, direction="out", subject="Ancien", sent_at=now - timedelta(days=40)))
        s.add(Message(contact_id=g, direction="in", kind="reply", subject="Re: Ancien", received_at=now - timedelta(days=39)))
        s.add(Message(contact_id=g, direction="out", subject="Nouveau", sent_at=now - timedelta(days=12)))
        s.commit()
        w = SendWindow.from_settings(s)
        assert g in [r["contact"].id for r in stats.followups(s, now, w, 3)]

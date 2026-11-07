"""V2.5 : relance à un jour précis (jour de la semaine + heure) et démarrage planifié."""
import random
from datetime import datetime, time, timedelta

import pytest
from sqlalchemy import select

from app import campaigns_service as camp_svc
from app import engine
from app import sequences_service as ss
from app.db import get_session
from app.models import Campaign, Enrollment, Sequence, Step
from app.scheduling import SendWindow
from datetime import timezone

from app.timeutil import TZ, to_local

UTC = timezone.utc
from tests.test_m4_engine import START, _run, world  # noqa: F401

ORIGIN = {"Origin": "http://testserver"}
W = SendWindow(frozenset(range(5)), ((time(9), time(12, 30)), (time(14, 30), time(17, 30))),
               frozenset({datetime(2026, 11, 18).date()}))  # 18/11 : fête de l'Indépendance


def L(*a):  # heure du Maroc -> UTC
    return datetime(*a, tzinfo=TZ).astimezone(UTC)


@pytest.mark.parametrize("prev, delay, weekday, at, expected", [
    # mardi 03/11 08:00 -> J+3 ouvrés = vendredi 06/11 (pas férié dans W) ; puis « mardi » -> mardi 10/11 ; 10:00
    (L(2026, 11, 3, 8), 3, 1, time(10), L(2026, 11, 10, 10)),
    # sans heure : ouverture de la fenêtre ce mardi-là
    (L(2026, 11, 3, 8), 3, 1, None, L(2026, 11, 10, 9)),
    # sans jour : J+2 à 15:00
    (L(2026, 11, 3, 8), 2, None, time(15), L(2026, 11, 5, 15)),
    # heure hors plages (13:00) : ramenée à la reprise de 14:30
    (L(2026, 11, 3, 8), 1, None, time(13), L(2026, 11, 4, 14, 30)),
    # le jour voulu tombe un férié (mercredi 18/11) : prochaine ouverture, jeudi 09:00
    (L(2026, 11, 12, 8), 3, 2, time(10), L(2026, 11, 19, 9)),
    # délai 0, « mardi 10:00 », et l'on est mardi 11:00 : la semaine suivante
    (L(2026, 11, 3, 11), 0, 1, time(10), L(2026, 11, 10, 10)),
    # délai 0, « mardi 10:00 », et l'on est mardi 08:00 : le jour même
    (L(2026, 11, 3, 8), 0, 1, time(10), L(2026, 11, 3, 10)),
])
def test_due_after_specific_day_and_time(prev, delay, weekday, at, expected):
    assert W.due_after(prev, delay, True, weekday, at) == expected


def test_without_options_behaviour_unchanged():
    assert W.due_after(L(2026, 11, 3, 8), 3, True) == L(2026, 11, 6, 9)
    assert W.due_after(L(2026, 11, 3, 10), 0, True) == L(2026, 11, 3, 10)


def test_sequence_api_saves_day_and_time(client, world):  # noqa: F811
    seq = client.get("/api/sequences").json()["items"][0]
    full = client.get(f"/api/sequences/{seq['id']}").json()
    steps = full["steps"]
    steps[1].update(weekday=1, send_time="10:00")
    r = client.put(f"/api/sequences/{seq['id']}", json={"name": full["name"], "steps": steps}, headers=ORIGIN)
    assert r.status_code == 200
    again = client.get(f"/api/sequences/{seq['id']}").json()["steps"][1]
    assert (again["weekday"], again["send_time"]) == (1, "10:00")
    steps[1].update(weekday=5)  # samedi : refusé
    assert client.put(f"/api/sequences/{seq['id']}", json={"name": full["name"], "steps": steps}, headers=ORIGIN).status_code == 422
    steps[1].update(weekday=None, send_time="25:00")
    assert client.put(f"/api/sequences/{seq['id']}", json={"name": full["name"], "steps": steps}, headers=ORIGIN).status_code == 422


def test_engine_schedules_followup_on_chosen_day(world):  # noqa: F811
    with get_session() as s:
        seq = s.scalars(select(Sequence)).first()
        st2 = ss.steps_of(s, seq)[1]
        st2.delay_days, st2.weekday, st2.send_time = 2, 3, "10:30"  # au moins J+2, puis jeudi 10:30
        camp = s.get(Campaign, world["campaign_id"])
        camp_svc.activate(s, camp, include_overlapping=False, now=START, rng=random.Random(1))
        s.commit()
    _run(until=START + timedelta(hours=4))  # les 1ers emails partent mardi 03/11 au matin
    with get_session() as s:
        dues = {to_local(e.next_due_at) for e in s.scalars(select(Enrollment)) if e.current_step == 2}
    assert dues == {datetime(2026, 11, 5, 10, 30, tzinfo=TZ)}  # jeudi 05/11 10:30


def test_planned_start(world, client):  # noqa: F811
    start = L(2026, 11, 9, 10)  # lundi 09/11 10:00
    with get_session() as s:
        camp = s.get(Campaign, world["campaign_id"])
        camp.start_at = start
        n = camp_svc.activate(s, camp, include_overlapping=False, now=START, rng=random.Random(1))
        s.commit()
        assert {e.next_due_at for e in s.scalars(select(Enrollment))} == {start}
    _run(until=START + timedelta(days=5))  # rien ne part avant le lundi
    assert world["smtp"].messages == []
    _run(until=start + timedelta(hours=3), now=start)
    assert len(world["smtp"].messages) == n


def test_start_api_create_reschedule_and_lock(client, world):  # noqa: F811
    future = (datetime.now(UTC) + timedelta(days=3)).replace(microsecond=0)
    r = client.put(f"/api/campaigns/{world['campaign_id']}/start", json={"start_at": future.isoformat()}, headers=ORIGIN)
    assert r.status_code == 200
    d = client.get(f"/api/campaigns/{world['campaign_id']}").json()
    assert d["start_at"] == future.isoformat().replace("+00:00", "Z") or d["start_at"].startswith(future.strftime("%Y-%m-%dT%H:%M"))
    rep = client.get(f"/api/campaigns/{world['campaign_id']}/activation").json()
    assert rep["first_send"] >= future.strftime("%Y-%m-%d")  # l'estimation part du démarrage
    past = (datetime.now(UTC) - timedelta(days=1)).isoformat()
    assert client.put(f"/api/campaigns/{world['campaign_id']}/start", json={"start_at": past}, headers=ORIGIN).status_code == 409
    # une fois des emails partis, le démarrage ne bouge plus
    with get_session() as s:
        camp = s.get(Campaign, world["campaign_id"])
        camp.start_at = None
        camp_svc.activate(s, camp, include_overlapping=False, now=START, rng=random.Random(1))
        s.commit()
    _run(until=START + timedelta(hours=2))
    later = client.put(f"/api/campaigns/{world['campaign_id']}/start", json={"start_at": future.isoformat()}, headers=ORIGIN)
    assert later.status_code == 409


def test_preview_dates_follow_day_and_time(world):  # noqa: F811
    with get_session() as s:
        seq = s.scalars(select(Sequence)).first()
        steps = ss.steps_of(s, seq)
        steps[0].send_time = "11:00"
        steps[1].delay_days, steps[1].weekday, steps[1].send_time = 1, 4, None
        dates = [to_local(d) for d in __import__("app.scheduling", fromlist=["planned_dates"]).planned_dates(
            SendWindow.from_settings(s), START, steps[:2])]
    # « vendredi » = 06/11, Marche verte (férié dans les réglages) : prochaine ouverture, lundi 09/11
    assert dates[0] == datetime(2026, 11, 3, 11, tzinfo=TZ) and dates[1] == datetime(2026, 11, 9, 9, tzinfo=TZ)

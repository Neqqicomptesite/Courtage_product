import pytest
"""V2.20 : essai d'endurance du moteur avant le déploiement au cabinet.

40 contacts × 3 étapes sur 6 semaines simulées, avec des pannes : 15 % des envois SMTP
échouent (coupure), le PC est éteint deux jours, 6 personnes répondent en cours de route.
On vérifie les promesses faites à Omar :
- personne ne reçoit deux fois la même étape ;
- personne ne reçoit plus rien après avoir répondu ;
- tous les autres reçoivent toute la séquence ;
- jamais plus de 25 envois par jour ni 10 par heure, jamais hors des heures et jours ouvrés ;
- en mode test, rien ne part chez les contacts.
"""
import random
from collections import Counter
from datetime import timedelta

from sqlalchemy import update, select

from app import engine
from app.db import get_session
from app.models import Contact, Enrollment, Message
from app.scheduling import SendWindow
from app.timeutil import to_local
from tests.conftest import USER
from tests.test_m4_engine import START, _activate, world  # noqa: F401


def test_soak_six_weeks_with_failures(world):  # noqa: F811
    with get_session() as s:
        for i in range(3, 40):
            s.add(Contact(email=f"p{i}@entreprise{i}.ma", first_name=f"P{i}", last_name="Test",
                          company=f"Entreprise {i}", sequence_code=["FIN-IND", "RH-BTP", "DIR-SRV"][i % 3],
                          email_reliability="Bonne (test)"))
        s.commit()
    assert _activate(world["campaign_id"]) == 40

    rng = random.Random(2026)
    failures = {"n": 0}

    def flaky_smtp(cfg):
        if rng.random() < 0.15:
            failures["n"] += 1
            raise ConnectionResetError("coupure réseau simulée")
        return engine.transport.open_smtp(cfg)

    replied: dict[int, object] = {}
    off = (START + timedelta(days=8), START + timedelta(days=10))  # PC éteint deux jours
    now, end = START, START + timedelta(days=42)
    with get_session() as s:
        window = SendWindow.from_settings(s)
        # les inscriptions datent du début de la simulation, pas de l'horloge réelle : sinon, le jour où
        # la simulation traverse la date réelle, une réponse simulée paraît antérieure à l'inscription
        s.execute(update(Enrollment).values(created_at=START))
        s.commit()
    ticks = 0
    while now < end and ticks < 20000:
        ticks += 1
        if off[0] <= now < off[1]:
            now = off[1]
            continue
        if len(replied) < 6 and now >= START + timedelta(days=3, hours=len(replied) * 7):
            with get_session() as s:  # une personne de plus répond
                c = s.scalars(select(Contact).where(Contact.id.not_in(list(replied) or [0]))
                              .order_by(Contact.id.desc())).first()
                s.add(Message(contact_id=c.id, direction="in", kind="reply", subject="Re: …", received_at=now))
                s.commit()
                replied[c.id] = now
        r = engine.tick(now=now, smtp_factory=flaky_smtp, rng=rng, sync=False)
        assert r.action not in ("busy",), r
        if r.action == "sent" or not window.is_open(now):
            now = window.next_open(now + timedelta(minutes=1)) if not window.is_open(now) else now + timedelta(minutes=1)
        else:
            now += timedelta(minutes=10)

    assert failures["n"] > 5  # les pannes ont bien eu lieu
    with get_session() as s:
        sent = list(s.scalars(select(Message).where(Message.direction == "out", Message.sent_at.is_not(None))))
        enrollments = list(s.scalars(select(Enrollment)))
        steps_by_contact: dict[int, list[int]] = {}
        for m in sent:
            steps_by_contact.setdefault(m.contact_id, []).append(m.step_position)
            assert m.to_email == USER  # mode test : tout part chez Omar
            local = to_local(m.sent_at)
            assert window.is_open(m.sent_at), f"envoi hors fenêtre : {local}"
            assert not (off[0] <= m.sent_at < off[1])
            if m.contact_id in replied:
                assert m.sent_at <= replied[m.contact_id], "relance partie après une réponse"
        for cid, steps in steps_by_contact.items():
            assert len(steps) == len(set(steps)), f"étape envoyée deux fois au contact {cid}"
        for e in enrollments:
            if e.contact_id not in replied:
                assert sorted(steps_by_contact.get(e.contact_id, [])) == [1, 2, 3], (e.contact_id, e.status, e.last_error)
        per_day = Counter(to_local(m.sent_at).date() for m in sent)
        assert max(per_day.values()) <= 25
        times = sorted(m.sent_at for m in sent)
        for i, t in enumerate(times):
            assert sum(1 for u in times[i:] if u < t + timedelta(hours=1)) <= 10
    assert len(world["smtp"].messages) == len(sent)  # un email parti = un email enregistré


def test_backups_keep_recent_and_one_per_day(db, monkeypatch, tmp_path):
    """Constaté chez Omar : une journée de redémarrages effaçait les jours précédents."""
    from datetime import datetime
    from app import backup
    from app.timeutil import TZ
    folder = tmp_path / "b"
    folder.mkdir()
    monkeypatch.setattr(backup, "utcnow", lambda: datetime(2026, 11, 20, 12, 0, tzinfo=TZ))
    names = [f"oddo_2026-11-{d:02d}_0{h}0000_demarrage.db" for d in range(1, 21) for h in range(1, 4)]
    names.append("oddo_2026-09-01_100000_demarrage.db")  # plus de 30 jours
    for n in names:
        (folder / n).write_bytes(b"x")
    backup._prune(folder)
    left = sorted(p.name for p in folder.iterdir())
    days = {n[5:15] for n in left}
    assert len(days) == 20 and "2026-09-01" not in days            # un par jour sur 30 jours
    assert all(f"oddo_2026-11-20_0{h}0000_demarrage.db" in left for h in (1, 2, 3))  # les dernières gardées
    assert len(left) <= backup.KEEP + 20


@pytest.mark.sqlite_only
def test_daily_backup_runs_when_last_is_old(db, monkeypatch, tmp_path):
    import os
    import time
    from app import backup
    monkeypatch.setattr(backup, "backups_dir", lambda: tmp_path)
    assert backup.daily_if_due() is not None          # aucune sauvegarde : on en fait une
    assert backup.daily_if_due() is None              # récente : rien
    old = time.time() - 21 * 3600
    for p in tmp_path.glob("oddo_*.db"):
        os.utime(p, (old, old))
    assert backup.daily_if_due() is not None

"""V3.7.2 : vider « Envoyés sans réponse » (retirer une, plusieurs ou toutes les personnes), avec Annuler ;
une personne retirée revient si on lui écrit de nouveau."""
from datetime import timedelta

from sqlalchemy import select

from app import engine, stats
from app.db import get_session
from app.models import Enrollment, Message
from app.scheduling import SendWindow
from tests.test_m4_engine import world  # noqa: F401
from tests.test_v223 import OV, ORIGIN, _setup


def _listed(now, g):
    with get_session() as s:
        return g in [r["contact"].id for r in stats.followups(s, now, SendWindow.from_settings(s), 3)]


def test_dismiss_restore_and_comes_back_after_a_new_email(client, world):  # noqa: F811
    g, _, seq = _setup()
    client.post(f"/api/sequences/{seq['G1']}/send", json={"contact_ids": [g], "overrides": OV}, headers=ORIGIN)
    with get_session() as s:
        now = SendWindow.from_settings(s).next_open(s.scalars(select(Enrollment)).one().next_due_at)
    engine.tick(now=now, sync=False)
    later = now + timedelta(days=6)
    assert _listed(later, g)
    assert client.post("/api/followups/dismiss", json={"contact_ids": [g, "x"]}, headers=ORIGIN).json() == {"dismissed": 1}
    assert not _listed(later, g)
    client.post("/api/followups/restore", json={"contact_ids": [g]}, headers=ORIGIN)
    assert _listed(later, g)                                                     # Annuler
    client.post("/api/followups/dismiss", json={"contact_ids": [g]}, headers=ORIGIN)
    with get_session() as s:                                                     # un nouvel email part plus tard
        m = s.scalars(select(Message).where(Message.contact_id == g, Message.direction == "out")).first()
        s.add(Message(contact_id=g, direction="out", kind=m.kind, subject="Relance", body_text="x",
                      to_email=m.to_email, sent_at=m.sent_at + timedelta(days=1), test_mode=False))
        s.commit()
    assert _listed(later + timedelta(days=5), g)                                 # il revient

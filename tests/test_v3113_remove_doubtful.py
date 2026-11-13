"""V3.11.3 : retirer d'une campagne déjà lancée les contacts à l'email douteux."""
from sqlalchemy import select

from app.db import get_session
from app.models import Contact, Enrollment, Message
from tests.test_m4_engine import ORIGIN, START, _activate, world  # noqa: F401


def test_remove_doubtful_from_a_running_campaign(client, world):  # noqa: F811
    _activate(world["campaign_id"])
    cid = world["campaign_id"]
    with get_session() as s:
        cs = list(s.scalars(select(Contact).order_by(Contact.id)))
        cs[0].email_reliability = "À vérifier"
        s.add(Message(direction="in", kind="bounce_soft", contact_id=cs[1].id, received_at=START, test_mode=False, subject="x"))
        s.commit()
        ids = [cs[0].id, cs[1].id]
    items = client.get(f"/api/campaigns/{cid}/doubtful").json()["items"]
    assert sorted(i["contact"]["id"] for i in items) == sorted(ids)
    assert {i["reason"] for i in items} == {"qualité « À vérifier »", "a déjà rebondi"}
    one = [i["enrollment_id"] for i in items if i["contact"]["id"] == ids[0]]
    r = client.post(f"/api/campaigns/{cid}/remove-doubtful", json={"enrollment_ids": one}, headers=ORIGIN)
    assert r.json().get("removed") == 1, r.text
    assert client.post(f"/api/campaigns/{cid}/remove-doubtful", json={}, headers=ORIGIN).json()["removed"] == 1
    with get_session() as s:
        st = {e.contact_id: (e.status, e.stop_reason) for e in s.scalars(select(Enrollment).where(Enrollment.campaign_id == cid))}
        assert st[ids[0]] == ("stopped", "manual_removed") and st[ids[1]] == ("stopped", "manual_removed")
        assert sum(1 for k, v in st.items() if v[0] == "scheduled") == 1   # le contact sûr continue
    assert client.get(f"/api/campaigns/{cid}/doubtful").json()["items"] == []

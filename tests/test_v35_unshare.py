"""V3.5 : un modèle partagé avec l'équipe peut repasser en perso (administrateur), sauf si un
collègue l'utilise dans une campagne."""
from sqlalchemy import select

from app.db import get_session
from app.models import Campaign, Mailbox, Sequence
from tests.test_v3_auth import H, _two_boxes, server  # noqa: F401


def test_share_then_unshare(server):  # noqa: F811
    _two_boxes()
    sid = server.post("/api/sequences", json={"name": "Relance BTP", "steps": 2}, headers=H("omar@oddo.ma")).json()["id"]
    names = lambda who: {q["name"] for q in server.get("/api/sequences", headers=H(who)).json()["items"]}  # noqa: E731
    assert server.post(f"/api/sequences/{sid}/share", headers=H("omar@oddo.ma")).json()["shared"] is True
    assert "Relance BTP" in names("hamza@oddo.ma")
    assert server.post(f"/api/sequences/{sid}/unshare", headers=H("hamza@oddo.ma")).status_code == 403  # pas admin
    r = server.post(f"/api/sequences/{sid}/unshare", headers=H("omar@oddo.ma")).json()
    assert r["shared"] is False and r["editable"] is True
    assert "Relance BTP" not in names("hamza@oddo.ma") and "Relance BTP" in names("omar@oddo.ma")
    assert server.post(f"/api/sequences/{sid}/unshare", headers=H("omar@oddo.ma")).status_code == 409  # déjà perso
    # repartagée, puis utilisée par Hamza : elle ne peut plus redevenir perso
    server.post(f"/api/sequences/{sid}/share", headers=H("omar@oddo.ma"))
    with get_session() as s:
        mb_h = s.scalars(select(Mailbox.id).where(Mailbox.email == "hamza@oddo.ma")).one()
        s.add(Campaign(name="Campagne de Hamza", mailbox_id=mb_h, sequence_id=sid, filters={}, status="active"))
        s.commit()
    r = server.post(f"/api/sequences/{sid}/unshare", headers=H("omar@oddo.ma"))
    assert r.status_code == 409 and "collègue" in r.json()["detail"]
    with get_session() as s:
        assert s.get(Sequence, sid).owner_id is None

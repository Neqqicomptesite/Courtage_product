"""V3.6 : listes de contacts (personnelles, partageables), filtre des campagnes, sans-réponse."""
from sqlalchemy import select

from app import campaigns_service as camp_svc
from app.db import get_session
from app.models import Campaign, Contact, Enrollment, Mailbox
from tests.test_m4_engine import ORIGIN, START, world  # noqa: F401
from tests.test_v3_auth import H, _two_boxes, server  # noqa: F401


def _ids(world_):
    with get_session() as s:
        return [c.id for c in s.scalars(select(Contact).order_by(Contact.id))]


def test_list_lifecycle_and_campaign_filter(client, world):  # noqa: F811
    ids = _ids(world)
    cl = client.post("/api/lists", json={"name": "  Salon   BTP 2026 ", "contact_ids": ids[:2]}, headers=ORIGIN).json()
    assert (cl["name"], cl["count"], cl["shared"], cl["editable"], cl["source"]) == ("Salon BTP 2026", 2, False, True, "manual")
    lid = cl["id"]
    r = client.post(f"/api/lists/{lid}/members", json={"contact_ids": [ids[1], ids[2], 99999]}, headers=ORIGIN).json()
    assert r["added"] == 1 and r["count"] == 3                       # pas de doublon, inconnus ignorés
    r = client.post(f"/api/lists/{lid}/members/remove", json={"contact_ids": [ids[0]]}, headers=ORIGIN).json()
    assert r["removed"] == 1 and r["count"] == 2
    assert client.put(f"/api/lists/{lid}", json={"name": "Salon BTP"}, headers=ORIGIN).json()["name"] == "Salon BTP"
    assert client.post("/api/lists", json={"name": "   "}, headers=ORIGIN).status_code == 422
    # filtre dans Contacts et dans l'assistant de campagne
    assert {c["id"] for c in client.get(f"/api/contacts?list_id={lid}").json()["items"]} == set(ids[1:3])
    assert client.get(f"/api/contacts/count?list_id={lid}").json()["matching"] == 2
    assert "list_id" in camp_svc.FILTER_KEYS
    with get_session() as s:
        camp = s.get(Campaign, world["campaign_id"])
        camp.filters = {"list_id": str(lid)}
        s.commit()
        assert {c.contact.id for c in camp_svc.candidates(s, camp, check_render=False, now=START)} == set(ids[1:3])
    # la fiche d'un contact montre ses listes
    assert client.get(f"/api/contacts/{ids[1]}").json()["lists"] == [{"id": lid, "name": "Salon BTP"}]
    # supprimer la liste ne supprime aucun contact
    assert client.delete(f"/api/lists/{lid}", headers=ORIGIN).json()["ok"]
    assert client.get("/api/lists").json()["items"] == [] and len(_ids(world)) == len(ids)


def test_no_reply_list_from_campaign(client, world):  # noqa: F811
    ids = _ids(world)
    with get_session() as s:
        for cid, st in zip(ids, ("completed", "replied", "completed")):
            s.add(Enrollment(campaign_id=world["campaign_id"], contact_id=cid, status=st))
        s.commit()
    cl = client.post(f"/api/campaigns/{world['campaign_id']}/no-reply-list", headers=ORIGIN).json()
    assert cl["count"] == 2 and cl["source"] == "campaign" and cl["name"].startswith("Sans réponse · ")
    assert client.post("/api/campaigns/999/no-reply-list", headers=ORIGIN).status_code == 404


def test_personal_then_shared(server):  # noqa: F811
    _two_boxes()
    with get_session() as s:
        s.add(Contact(email="a@client.ma", first_name="A"))
        s.commit()
        cid = s.scalars(select(Contact.id)).first()
    lid = server.post("/api/lists", json={"name": "Mes prospects", "contact_ids": [cid]}, headers=H("hamza@oddo.ma")).json()["id"]
    names = lambda who: [x["name"] for x in server.get("/api/lists", headers=H(who)).json()["items"]]  # noqa: E731
    assert names("hamza@oddo.ma") == ["Mes prospects"] and names("omar@oddo.ma") == []   # personnelle
    assert len(server.get(f"/api/contacts?list_id={lid}", headers=H("omar@oddo.ma")).json()["items"]) == 0  # invisible
    assert server.post(f"/api/lists/{lid}/share", json={"shared": True}, headers=H("hamza@oddo.ma")).json()["shared"]
    seen = server.get("/api/lists", headers=H("omar@oddo.ma")).json()["items"][0]
    assert seen["name"] == "Mes prospects" and seen["mine"] is False and seen["owner"]
    assert len(server.get(f"/api/contacts?list_id={lid}", headers=H("omar@oddo.ma")).json()["items"]) == 1
    # Omar est administrateur : il peut la modifier ; un employé ne modifie pas la liste d'un collègue
    lid2 = server.post("/api/lists", json={"name": "Liste d'Omar"}, headers=H("omar@oddo.ma")).json()["id"]
    server.post(f"/api/lists/{lid2}/share", json={"shared": True}, headers=H("omar@oddo.ma"))
    assert server.put(f"/api/lists/{lid2}", json={"name": "X"}, headers=H("hamza@oddo.ma")).status_code == 403
    assert server.delete(f"/api/lists/{lid2}", headers=H("hamza@oddo.ma")).status_code == 403

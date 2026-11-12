"""V3.9.2 : brouillons des emails écrits dans l'appli."""
from app import mail_drafts
from app.current import as_user
from app.db import get_session
from app.models import AppUser
from tests.test_m4_engine import ORIGIN, world  # noqa: F401


def test_draft_is_saved_updated_reopened_and_deleted(client, db):
    up = client.post("/api/mailbox/drafts", json={"to": "yassine@x.ma", "subject": "Cotation flotte", "body": "Bonjour Yassine,\n\nVoici",
                                                  "cc": "a@x.ma", "in_reply_to": "<m1@x>", "references": ["<m1@x>"],
                                                  "quote": {"from": "Yassine", "date": None, "text": "Bonjour"}, "with_quote": False},
                     headers=ORIGIN).json()
    did = up["id"]
    assert did
    again = client.post("/api/mailbox/drafts", json={"id": did, "to": "yassine@x.ma", "subject": "Cotation flotte (2)", "body": "Bonjour Yassine,\n\nVoici la suite"},
                        headers=ORIGIN).json()
    assert again["id"] == did                                    # même brouillon, mis à jour
    items = client.get("/api/mailbox/drafts").json()["items"]
    assert [i["id"] for i in items] == [did] and items[0]["subject"] == "Cotation flotte (2)" and "la suite" in items[0]["snippet"]
    full = client.get(f"/api/mailbox/drafts/{did}").json()
    assert full["body"].endswith("la suite") and full["attachments"] == []
    assert client.delete(f"/api/mailbox/drafts/{did}", headers=ORIGIN).json()["ok"]
    assert client.get("/api/mailbox/drafts").json()["items"] == []
    assert client.get(f"/api/mailbox/drafts/{did}").status_code == 404


def test_empty_draft_is_not_kept(client, db):
    assert client.post("/api/mailbox/drafts", json={"to": "", "subject": " ", "body": ""}, headers=ORIGIN).json()["id"] is None
    did = client.post("/api/mailbox/drafts", json={"body": "x"}, headers=ORIGIN).json()["id"]
    assert client.post("/api/mailbox/drafts", json={"id": did, "body": ""}, headers=ORIGIN).json()["id"] is None  # tout effacé
    assert client.get("/api/mailbox/drafts").json()["items"] == []


def test_sending_removes_the_draft(client, world):  # noqa: F811
    did = client.post("/api/mailbox/drafts", json={"to": "client@x.ma", "subject": "Hello", "body": "Bonjour"}, headers=ORIGIN).json()["id"]
    r = client.post("/api/mailbox/send", json={"to": "client@x.ma", "subject": "Hello", "body": "Bonjour", "draft_id": did}, headers=ORIGIN)
    assert r.status_code == 200, r.text
    assert world["smtp"].messages
    assert client.get("/api/mailbox/drafts").json()["items"] == []


def test_failed_send_keeps_the_draft(client, world):  # noqa: F811
    did = client.post("/api/mailbox/drafts", json={"to": "pas-une-adresse", "body": "Bonjour"}, headers=ORIGIN).json()["id"]
    r = client.post("/api/mailbox/send", json={"to": "pas-une-adresse", "subject": "", "body": "Bonjour", "draft_id": did}, headers=ORIGIN)
    assert r.status_code >= 400
    assert [i["id"] for i in client.get("/api/mailbox/drafts").json()["items"]] == [did]


def test_drafts_are_private_to_each_employee(db):
    with get_session() as s:
        a, b = AppUser(email="a@oddo.ma", full_name="A"), AppUser(email="b@oddo.ma", full_name="B")
        s.add_all([a, b])
        s.commit()
        ida, idb = a.id, b.id
    with as_user(ida), get_session() as s:
        did = mail_drafts.save(s, {"to": "x@y.ma", "body": "secret"}).id
        s.commit()
    with as_user(idb), get_session() as s:
        assert mail_drafts.listing(s) == [] and mail_drafts.get(s, did) is None
        assert not mail_drafts.delete(s, did)
        other = mail_drafts.save(s, {"body": "à moi"}, did)   # le numéro d'un collègue : nouveau brouillon
        s.commit()
        assert other.id != did and other.user_id == idb
    with as_user(ida), get_session() as s:
        assert [d["snippet"] for d in mail_drafts.listing(s)] == ["secret"]

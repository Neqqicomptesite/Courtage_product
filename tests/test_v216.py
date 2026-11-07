"""V2.16 : guide de démarrage (« Bien démarrer » : étapes cochées d'elles-mêmes ou à la main)."""
from app import settings_store
from app.db import get_session
from app.models import Contact, Mailbox

ORIGIN = {"Origin": "http://testserver"}


def test_guide_progress(client, db):
    g = client.get("/api/guide").json()
    assert g["total"] == 5 and not g["steps"]["mailbox"] and not g["steps"]["real"]
    with get_session() as s:
        s.add(Mailbox(display_name="A", email="a@oddo.ma", smtp_host="h", imap_host="h", signature="A\nODDO"))
        settings_store.set_(s, "last_imap_sync", "2026-11-04T10:00:00+00:00")
        s.add(Contact(email="p@x.ma", kind="prospect"))
        s.commit()
    st = client.get("/api/guide").json()["steps"]
    assert st["mailbox"] and st["signature"] and st["contacts"] and not st["test"]
    r = client.post("/api/guide", json={"key": "test", "done": True}, headers=ORIGIN).json()
    assert r["steps"]["test"] and r["done"] == 4
    assert client.post("/api/guide", json={"key": "real"}, headers=ORIGIN).status_code == 400
    r = client.post("/api/guide", json={"key": "test", "done": False}, headers=ORIGIN).json()
    assert not r["steps"]["test"]

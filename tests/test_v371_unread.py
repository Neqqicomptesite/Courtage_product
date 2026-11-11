"""V3.7.1 : nombre de non lus (pastille du menu), et lu / non lu sur le serveur, comme une messagerie."""
from app import mailbox_browser
from tests.test_v24 import ORIGIN, _flags, box  # noqa: F401
from tests.test_m4_engine import world  # noqa: F401


def test_unread_badge_and_mark_seen(client, box):  # noqa: F811
    imap = box["imap"]
    assert client.get("/api/mailbox/unread").json() == {"unread": 3}
    items = client.get("/api/mailbox/messages?folder=INBOX&days=30").json()["items"]
    uid = next(m["uid"] for m in items if m["from_email"] == "ali@inconnu.ma")
    assert client.post(f"/api/mailbox/messages/{uid}/seen?folder=INBOX", headers=ORIGIN).json() == {"ok": True, "seen": True}
    assert sum("\\Seen" in f for f in _flags(imap)) == 1                       # lu sur le serveur (donc aussi dans le webmail)
    assert client.get("/api/mailbox/unread").json() == {"unread": 2}            # le compteur suit tout de suite
    again = client.get("/api/mailbox/messages?folder=INBOX&days=30").json()["items"]
    assert next(m for m in again if m["uid"] == uid)["seen"] is True            # la liste en mémoire aussi
    client.post(f"/api/mailbox/messages/{uid}/seen?folder=INBOX&seen=false", headers=ORIGIN)
    assert sum("\\Seen" in f for f in _flags(imap)) == 0
    assert client.get("/api/mailbox/unread").json() == {"unread": 3}


def test_unread_is_cached(client, box):  # noqa: F811
    client.get("/api/mailbox/unread")
    n = len(box["imap"].commands)
    client.get("/api/mailbox/unread")
    assert len(box["imap"].commands) == n                                       # pas de nouvelle connexion
    mailbox_browser.invalidate("INBOX")
    client.get("/api/mailbox/unread")
    assert len(box["imap"].commands) > n

"""V2.19 : emails reçus avec mise en forme, photos intégrées et pièces jointes ouvrables."""
from email.message import EmailMessage

import pytest

from app import mailbox_browser
from app.timeutil import utcnow
from tests.conftest import USER
from tests.test_m4_engine import world  # noqa: F401

PNG = bytes.fromhex("89504e470d0a1a0a0000000d4948445200000001000000010806000000"
                    "1f15c4890000000d49444154789c6360000002000154a24f5d0000000049454e44ae426082")


def rich_email() -> bytes:
    m = EmailMessage()
    m["From"], m["To"], m["Subject"], m["Message-ID"] = "Assureur <s@assureur.ma>", USER, "Avenant", "<av@assureur.ma>"
    m["Date"] = "Wed, 04 Nov 2026 09:00:00 +0000"
    m.set_content("Bonjour, voir l'avenant.")
    m.add_alternative('<p>Bonjour, voir <b>l\'avenant</b>.</p><img src="cid:logo123"><img src="https://pixel.ex/t.gif">'
                      '<script>alert(1)</script><meta http-equiv="refresh" content="0;url=https://x">', subtype="html")
    m.get_payload()[1].add_related(PNG, maintype="image", subtype="png", cid="<logo123>")
    m.add_attachment(b"%PDF-1.4 avenant", maintype="application", subtype="pdf", filename="Avenant 40123.pdf")
    m.add_attachment(b"PK docx", maintype="application",
                     subtype="vnd.openxmlformats-officedocument.wordprocessingml.document", filename="courrier.docx")
    m.add_attachment(b"<script>alert(1)</script>", maintype="text", subtype="html", filename="piege.html")
    return m.as_bytes()


@pytest.fixture
def box(world, client):  # noqa: F811
    mailbox_browser.invalidate()
    world["imap"].deliver("INBOX", rich_email(), utcnow().date())
    yield world
    mailbox_browser.invalidate()


def test_html_and_attachments(client, box):
    uid = client.get("/api/mailbox/messages?folder=INBOX&days=30").json()["items"][0]["uid"]
    m = client.get(f"/api/mailbox/messages/{uid}?folder=INBOX").json()
    assert "<b>l'avenant</b>" in m["html"] and "<script" not in m["html"] and "refresh" not in m["html"]
    assert "cid:" not in m["html"] and f"/api/mailbox/messages/{uid}/part/" in m["html"]
    assert m["remote_images"] is True
    names = [a["name"] for a in m["attachments"]]
    assert names == ["Avenant 40123.pdf", "courrier.docx", "piege.html"]  # l'image intégrée n'est pas listée
    by = {a["name"]: a for a in m["attachments"]}
    assert by["Avenant 40123.pdf"]["viewable"] and not by["courrier.docx"]["viewable"] and not by["piege.html"]["viewable"]

    img_url = m["html"].split('src="')[1].split('"')[0]
    r = client.get(img_url)
    assert r.status_code == 200 and r.content == PNG and r.headers["content-type"] == "image/png"
    assert r.headers["x-content-type-options"] == "nosniff" and "sandbox" in r.headers["content-security-policy"]

    pdf = client.get(by["Avenant 40123.pdf"]["url"])
    assert pdf.headers["content-type"] == "application/pdf" and pdf.headers["content-disposition"].startswith("inline")
    assert "Avenant%2040123.pdf" in pdf.headers["content-disposition"]
    trap = client.get(by["piege.html"]["url"])
    assert trap.headers["content-type"] == "application/octet-stream"
    assert trap.headers["content-disposition"].startswith("attachment")
    dl = client.get(by["Avenant 40123.pdf"]["url"] + "&download=1")
    assert dl.headers["content-disposition"].startswith("attachment") and dl.content == b"%PDF-1.4 avenant"
    assert client.get(f"/api/mailbox/messages/{uid}/part/99?folder=INBOX").status_code == 503
    # rien n'est marqué comme lu, et l'email n'est relu qu'une fois sur le serveur (mémoire 2 min)
    assert all("\\Seen" not in f for _, f, _ in box["imap"].folders["INBOX"].messages)


def test_forward_keeps_attachments_and_photos(client, box):
    uid = client.get("/api/mailbox/messages?folder=INBOX&days=30").json()["items"][0]["uid"]
    r = client.post(f"/api/mailbox/messages/{uid}/forward?folder=INBOX", headers={"Origin": "http://testserver"}).json()
    names = [a["name"] for a in r["attachments"]]
    assert "Avenant 40123.pdf" in names and "courrier.docx" in names
    assert any(n.endswith(".png") for n in names)  # la photo du corps est reprise en pièce jointe
    assert r["skipped"] == []
    ids = [a["id"] for a in r["attachments"] if a["name"] != "piege.html"]
    sent = client.post("/api/mailbox/send", headers={"Origin": "http://testserver"},
                       json={"to": "collegue@oddo.ma", "subject": "TR: Avenant", "body": "Pour info.\n\n--- Message transféré ---",
                             "attachment_ids": ids})
    assert sent.status_code == 200, sent.text
    from email import message_from_bytes, policy
    last = box["smtp"].messages[-1]
    msg = message_from_bytes(last.data, policy=policy.default)
    got = sorted(p.get_filename() for p in msg.iter_attachments())
    assert "Avenant 40123.pdf" in got and "courrier.docx" in got and len(got) == len(ids)
    assert str(msg["Subject"]).startswith("[TEST") or "TR: Avenant" in str(msg["Subject"])


# ------------------------------------------------------------------ V2.20 : archiver

def _uid(client, subject):
    items = client.get("/api/mailbox/messages?folder=INBOX&days=30&refresh=1").json()["items"]
    return next(m["uid"] for m in items if m["subject"] == subject)


@pytest.mark.parametrize("caps", ["IMAP4rev1 SPECIAL-USE MOVE UIDPLUS", "IMAP4rev1 UIDPLUS"])
def test_archive_and_undo(client, box, caps):
    imap = box["imap"]
    imap.capabilities = caps
    other = EmailMessage()
    other["From"], other["To"], other["Subject"], other["Message-ID"] = "x@y.ma", USER, "Autre", "<autre@y.ma>"
    other.set_content("reste là")
    imap.deliver("INBOX", other.as_bytes(), utcnow().date(), flags=["\\Deleted"])  # un autre email marqué supprimé
    uid = _uid(client, "Avenant")
    r = client.post(f"/api/mailbox/messages/{uid}/archive?folder=INBOX", headers={"Origin": "http://testserver"})
    assert r.status_code == 200, r.text
    assert r.json()["archive_folder"] == "INBOX.Archive" and r.json()["message_id"] == "<av@assureur.ma>"
    assert [m[0] for m in imap.folders["INBOX.Archive"].messages] and len(imap.folders["INBOX"].messages) == 1
    assert imap.folders["INBOX"].messages[0][2].find(b"Autre") >= 0  # l'autre email n'a pas été effacé
    subjects = [m["subject"] for m in client.get("/api/mailbox/messages?folder=INBOX&days=30").json()["items"]]
    assert "Avenant" not in subjects
    back = client.post("/api/mailbox/unarchive", json={"message_id": "<av@assureur.ma>", "folder": "INBOX"},
                       headers={"Origin": "http://testserver"})
    assert back.status_code == 200 and not imap.folders["INBOX.Archive"].messages
    assert "Avenant" in [m["subject"] for m in client.get("/api/mailbox/messages?folder=INBOX&days=30").json()["items"]]
    # un dossier « Archives » existant est réutilisé (pas de doublon)
    uid = _uid(client, "Avenant")
    client.post(f"/api/mailbox/messages/{uid}/archive?folder=INBOX", headers={"Origin": "http://testserver"})
    assert sum(1 for n in imap.folders if "rchive" in n) == 1


def test_archive_refused_without_safe_move(client, box):
    box["imap"].capabilities = "IMAP4rev1"
    uid = _uid(client, "Avenant")
    r = client.post(f"/api/mailbox/messages/{uid}/archive?folder=INBOX", headers={"Origin": "http://testserver"})
    assert r.status_code == 503 and "sans risque" in r.json()["detail"]
    assert len(box["imap"].folders["INBOX"].messages) == 1

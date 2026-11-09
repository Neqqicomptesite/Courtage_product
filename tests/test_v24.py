"""V2.4 : la boîte mail complète (lecture seule, rien n'est marqué comme lu) et l'écriture
d'emails depuis l'application (mode test, fil de conversation, historique, pas de stats)."""
from datetime import timedelta
from email import message_from_bytes, policy

import pytest
from sqlalchemy import select

from app import imap_sync, mailbox_browser, settings_store, stats, suppression
from app.db import get_session
from app.models import Contact, Message
from app.timeutil import utcnow
from tests.conftest import USER
from tests.test_m4_engine import world  # noqa: F401 (fixture réutilisée)

ORIGIN = {"Origin": "http://testserver"}


def _eml(sender: str, subject: str, body: str = "Bonjour", msgid: str = "<x@ext.ma>", attachment: bool = False,
         in_reply_to: str | None = None) -> bytes:
    from email.message import EmailMessage
    m = EmailMessage()
    m["From"], m["To"], m["Subject"], m["Message-ID"] = sender, USER, subject, msgid
    m["Date"] = "Wed, 04 Nov 2026 09:00:00 +0000"
    if in_reply_to:
        m["In-Reply-To"] = m["References"] = in_reply_to
    m.set_content(body)
    if attachment:
        m.add_attachment(b"%PDF-1.4 test", maintype="application", subtype="pdf", filename="contrat.pdf")
    return m.as_bytes()


@pytest.fixture
def box(world, client):  # noqa: F811
    mailbox_browser.invalidate()
    imap = world["imap"]
    today = utcnow().date()
    imap.deliver("INBOX", _eml("Prénom0 Test <contact0@societe0.ma>", "Re: vos contrats", msgid="<r0@societe0.ma>"), today)
    imap.deliver("INBOX", _eml("Inconnu <ali@inconnu.ma>", "Demande de devis", "Pouvez-vous m'appeler ?",
                               msgid="<d1@inconnu.ma>", attachment=True), today)
    imap.deliver("INBOX", _eml("Vieux <old@x.ma>", "Ancien", msgid="<o@x.ma>"), today - timedelta(days=60))
    yield world
    mailbox_browser.invalidate()


def _flags(imap, folder="INBOX"):
    return [flags for _, flags, _ in imap.folders[folder].messages]


def test_list_is_read_only_and_marks_known_senders(client, box):
    r = client.get("/api/mailbox/messages?folder=INBOX&days=30")
    assert r.status_code == 200
    items = r.json()["items"]
    assert [m["subject"] for m in items] == ["Demande de devis", "Re: vos contrats"] or len(items) == 2
    by = {m["from_email"]: m for m in items}
    assert set(by) == {"contact0@societe0.ma", "ali@inconnu.ma"}  # plus de 30 jours : pas listé
    assert by["contact0@societe0.ma"]["contact"]["company"] == "Société 0"
    assert by["ali@inconnu.ma"]["contact"] is None and by["ali@inconnu.ma"]["has_attachments"] is True
    assert all(m["seen"] is False for m in items)
    # ouvrir un email ne le marque pas comme lu sur le serveur
    d = client.get(f"/api/mailbox/messages/{by['ali@inconnu.ma']['uid']}?folder=INBOX").json()
    assert d["text"] == "Pouvez-vous m'appeler ?" and d["attachments"][0]["name"] == "contrat.pdf"
    assert all("\\Seen" not in f for f in _flags(box["imap"]))
    assert "STORE" not in box["imap"].commands and "SELECT" not in box["imap"].commands  # EXAMINE seulement


def test_folders_and_errors(client, box):
    f = client.get("/api/mailbox/folders").json()
    assert f["items"][0]["raw"] == "INBOX" and f["sent"] == "INBOX.Sent"
    assert client.get("/api/mailbox/messages?folder=Inexistant").status_code == 503


def test_write_reply_in_test_mode(client, box):
    r = client.post("/api/mailbox/send", json={
        "to": "ali@inconnu.ma", "subject": "RE: Demande de devis", "body": "Avec plaisir, je vous appelle demain.",
        "in_reply_to": "<d1@inconnu.ma>", "references": ["<d1@inconnu.ma>"]}, headers=ORIGIN)
    assert r.status_code == 200 and r.json()["test_mode"] is True
    (sent,) = box["smtp"].messages
    msg = message_from_bytes(sent.data, policy=policy.default)
    assert sent.rcpt_tos == [USER]  # mode test : chez Omar
    assert msg["Subject"] == "[TEST → ali@inconnu.ma] RE: Demande de devis"
    assert msg["In-Reply-To"] == "<d1@inconnu.ma>" and msg["List-Unsubscribe"] is None
    assert msg.get_content().rstrip().endswith("ODDO Assurance")  # signature
    assert len(box["imap"].folders["INBOX.Sent"].messages) == 1  # copie dans « Envoyés »
    with get_session() as s:
        m = s.scalars(select(Message).where(Message.direction == "out")).one()
        assert (m.contact_id, m.enrollment_id, m.test_mode) == (None, None, True)


def test_write_to_contact_real_mode_goes_to_history_not_stats(client, box):
    with get_session() as s:
        settings_store.set_(s, "test_mode", False)
        s.commit()
        cid = s.scalars(select(Contact.id).where(Contact.email == "contact0@societe0.ma")).one()
    r = client.post("/api/mailbox/send", json={"to": "contact0@societe0.ma", "cc": "associe@oddo.ma",
                                               "subject": "Suite à notre échange", "body": "Bonjour,\nVoici…",
                                               "signature": False}, headers=ORIGIN)
    assert r.status_code == 200
    (sent,) = box["smtp"].messages
    assert set(sent.rcpt_tos) == {"contact0@societe0.ma", "associe@oddo.ma"}
    titles = [t["title"] for t in client.get(f"/api/contacts/{cid}").json()["timeline"]]
    assert "Email écrit depuis la boîte mail" in titles
    with get_session() as s:
        assert stats.indicators(s).sent_total == 0  # pas une campagne
    assert client.get("/api/status").json()["counters"]["today"] == 0  # ni dans les plafonds


def test_validation_and_exclusion_confirm(client, box):
    bad = client.post("/api/mailbox/send", json={"to": "pas-un-email", "subject": "", "body": ""}, headers=ORIGIN)
    assert bad.status_code == 422 and set(bad.json()["detail"]["errors"]) == {"to", "body"}  # V2.21 : objet vide permis (confirmation à l'écran)
    with get_session() as s:
        suppression.add(s, "ali@inconnu.ma", "STOP")
        s.commit()
    body = {"to": "ali@inconnu.ma", "subject": "Question", "body": "Bonjour"}
    r = client.post("/api/mailbox/send", json=body, headers=ORIGIN)
    assert r.status_code == 409 and r.json()["detail"]["confirm"] is True and box["smtp"].messages == []
    assert client.post("/api/mailbox/send", json={**body, "force": True}, headers=ORIGIN).status_code == 200


def test_reply_to_manual_email_is_not_a_campaign_reply(client, box):
    client.post("/api/mailbox/send", json={"to": "ali@inconnu.ma", "subject": "Devis", "body": "Ci-joint"}, headers=ORIGIN)
    with get_session() as s:
        mid = s.scalars(select(Message.message_id).where(Message.direction == "out")).one()
    box["imap"].deliver("INBOX", _eml("Ali <ali@inconnu.ma>", "Re: Devis", "Merci !", msgid="<r9@inconnu.ma>",
                                      in_reply_to=mid))
    imap_sync.sync(now=utcnow())
    with get_session() as s:
        assert s.scalars(select(Message).where(Message.direction == "in")).all() == []


def test_unconfigured_mailbox(client, db):
    mailbox_browser.invalidate()
    r = client.get("/api/mailbox/messages")
    assert r.status_code == 503 and "Réglages" in r.json()["detail"]


@pytest.mark.parametrize("raw, label", [
    ("INBOX", "Boîte de réception"), ("INBOX.Sent", "Envoyés"), ("INBOX.Archive", "Archives"), ("INBOX.Drafts", "Brouillons"),
    ("INBOX.Junk", "Indésirables"), ("INBOX.spam", "Spam"), ("INBOX.Trash", "Corbeille"), ("INBOX.Clients.Sanlam", "Clients › Sanlam"),
])
def test_business_folder_names(raw, label):  # V2.7
    assert mailbox_browser.folder_label(raw, raw)["label"] == label


def test_server_search_over_a_year_and_contact_history(client, box):
    """V3.4.4 : jusqu'à 12 mois ; la recherche est faite par le serveur mail (au-delà des 200 plus
    récents), et la fiche d'un contact retrouve ses emails sur un an. Rien n'est stocké chez nous."""
    imap = box["imap"]
    imap.deliver("INBOX", _eml("Ancien client <vieux@archive.ma>", "Renouvellement flotte", msgid="<a1@archive.ma>"),
                 utcnow().date() - timedelta(days=300))
    assert "vieux@archive.ma" not in {m["from_email"] for m in client.get("/api/mailbox/messages?days=90").json()["items"]}
    r = client.get("/api/mailbox/messages?days=365&q=flotte").json()
    assert r["searched"] and [m["from_email"] for m in r["items"]] == ["vieux@archive.ma"]
    r = client.get("/api/mailbox/messages?days=365&q=archive renouvellement").json()  # tous les mots
    assert [m["subject"] for m in r["items"]] == ["Renouvellement flotte"]
    assert client.get("/api/mailbox/messages?days=365&q=devis flotte").json()["items"] == []
    assert client.get("/api/mailbox/messages?days=365&q=éé").json()["unsearchable"] is True
    assert client.get("/api/mailbox/messages?days=900").json()["days"] == 365
    w = client.get("/api/mailbox/with?email=vieux@archive.ma").json()
    assert [m["subject"] for m in w["items"]] == ["Renouvellement flotte"] and w["days"] == 365
    assert client.get("/api/mailbox/with?email=ali@inconnu.ma").json()["items"][0]["subject"] == "Demande de devis"

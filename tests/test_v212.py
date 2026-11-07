"""V2.12 : « À répondre » (emails reçus restés sans réponse de ma part) et données de départ
des assureurs (logos + contacts)."""
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from email.utils import format_datetime

import pytest

from app import awaiting, mailbox_browser
from tests.conftest import USER
from tests.test_m4_engine import world  # noqa: F401

ORIGIN = {"Origin": "http://testserver"}
NOW = datetime(2026, 11, 13, 10, 0, tzinfo=timezone.utc)  # vendredi


def eml(sender, subject, when, msgid, to=USER, refs=None, headers=None):
    m = EmailMessage()
    m["From"], m["To"], m["Subject"], m["Message-ID"] = sender, to, subject, msgid
    m["Date"] = format_datetime(when)
    if refs:
        m["In-Reply-To"] = m["References"] = refs
    for k, v in (headers or {}).items():
        m[k] = v
    m.set_content("Bonjour")
    return m.as_bytes()


@pytest.fixture
def inbox(world):  # noqa: F811
    mailbox_browser.invalidate()
    imap = world["imap"]
    old = NOW - timedelta(days=7)   # 5 jours ouvrés avant
    recent = NOW - timedelta(days=1)
    put = lambda f, raw, when: imap.deliver(f, raw, when.date())  # noqa: E731
    put("INBOX", eml("Prénom0 Test <contact0@societe0.ma>", "Question contrat", old, "<a@s0.ma>"), old)
    put("INBOX", eml("Ali Inconnu <ali@inconnu.ma>", "Demande de devis", old, "<b@inconnu.ma>"), old)
    put("INBOX", eml("Karim <karim@client.ma>", "Sinistre", old, "<c@client.ma>"), old)          # répondu dans le fil
    put("INBOX", eml("Sara <sara@x.ma>", "Point", old, "<d@x.ma>"), old)                         # répondu par un email à elle
    put("INBOX", eml("Stripe <invoice+statements@stripe.com>", "Your receipt", old, "<e@stripe.com>"), old)
    put("INBOX", eml("News <hello@brand.ma>", "Promo", old, "<f@brand.ma>", headers={"List-Unsubscribe": "<mailto:u@brand.ma>"}), old)
    put("INBOX", eml("Lina <lina@y.ma>", "Hier", recent, "<g@y.ma>"), recent)                    # trop récent
    put("INBOX", eml("Absent <abs@z.ma>", "Réponse automatique : absent", old, "<h@z.ma>"), old)
    sent_when = NOW - timedelta(days=5)
    put("INBOX.Sent", eml(USER, "RE: Sinistre", sent_when, "<s1@oddo.ma>", to="karim@client.ma", refs="<c@client.ma>"), sent_when)
    put("INBOX.Sent", eml(USER, "Point", sent_when, "<s2@oddo.ma>", to="sara@x.ma"), sent_when)
    yield world
    mailbox_browser.invalidate()


def test_awaiting_reply(inbox):
    r = awaiting.awaiting(now=NOW)
    got = {i["from_email"]: i for i in r["items"]}
    assert set(got) == {"contact0@societe0.ma", "ali@inconnu.ma"}
    assert got["contact0@societe0.ma"]["contact"]["first_name"] == "Prénom0"
    assert got["ali@inconnu.ma"]["contact"] is None and got["ali@inconnu.ma"]["business_days"] >= 3


def test_awaiting_api(client, inbox, monkeypatch):
    real = awaiting.awaiting
    monkeypatch.setattr(awaiting, "awaiting", lambda refresh=False: real(now=NOW, refresh=refresh))
    r = client.get("/api/mailbox/awaiting").json()
    assert r["days"] == 3 and len(r["items"]) == 2


# ------------------------------------------------------------------ ligne STOP facultative

def test_unsubscribe_line_is_off_by_default(client, world, monkeypatch):  # noqa: F811
    from sqlalchemy import select

    from app import settings_store
    from app import sequences_service as ss
    from app.db import get_session
    from app.models import Campaign, Contact, Sequence
    monkeypatch.setattr(settings_store, "UNSUBSCRIBE_DEFAULT", False)
    with get_session() as s:
        seq = s.get(Sequence, s.get(Campaign, world["campaign_id"]).sequence_id)
        c = s.scalars(select(Contact)).first()
        assert ss.unsubscribe_for(s, seq) == ""
        assert "STOP" not in ss.preview(s, seq, c)[0].body
    st = client.get("/api/settings").json()["sending"]
    assert st["unsubscribe_enabled"] is False and st["unsubscribe_line"]
    st["unsubscribe_enabled"] = True
    assert client.put("/api/settings/sending", json=st, headers=ORIGIN).status_code == 200, "réactivable"
    with get_session() as s:
        assert "STOP" in ss.preview(s, s.get(Sequence, seq.id), s.get(Contact, c.id))[0].body


# ------------------------------------------------------------------ assureurs de départ

def test_starter_insurers(db):
    from sqlalchemy import func, select

    from app import starter_data
    from app.db import get_session
    from app.models import Company, Contact
    from app import companies_service as co
    data = starter_data.load()
    total = sum(len(c["people"]) for c in data["companies"])
    with get_session() as s:
        # une fiche « Sanlam » déjà là (prospect) et un contact existant avec des notes
        comp, _ = co.get_or_create(s, "Sanlam", "prospect")
        s.add(Contact(email="omar.seffar@sanlamallianz.ma", first_name="Omar", last_name="S.", company="Sanlam",
                      company_id=comp.id, kind="prospect", notes="déjà vu", source="Saisie manuelle"))
        s.commit()
        r = starter_data.apply(s)
        s.commit()
        assert r["companies_created"] == len(data["companies"]) - 1 and r["companies_updated"] == 1
        assert r["contacts_created"] == total - 1 and r["contacts_updated"] == 1
        sanlam = s.scalars(select(Company).where(Company.name == "Sanlam Allianz")).one()
        assert sanlam.id == comp.id and sanlam.kind == "insurer" and sanlam.logo
        omar = s.scalars(select(Contact).where(Contact.email == "omar.seffar@sanlamallianz.ma")).one()
        assert omar.notes == "déjà vu" and omar.kind == "insurer" and omar.department == "souscription"
        assert s.scalar(select(func.count(Contact.id)).where(Contact.kind == "insurer")) == total
        assert all(c.logo for c in s.scalars(select(Company)))
        # une deuxième fois : rien ne bouge
        assert starter_data.apply(s).get("skipped")
        assert s.scalar(select(func.count(Contact.id))) == total


def test_starter_logos_served(client, db):
    from app import starter_data
    from app.db import get_session
    with get_session() as s:
        starter_data.apply(s)
        s.commit()
    comps = client.get("/api/companies").json()["items"]
    axa = next(c for c in comps if c["name"].startswith("AXA"))
    r = client.get(axa["logo"])
    assert r.status_code == 200 and r.headers["content-type"] == "image/png"


def test_awaiting_dismiss_and_restore(client, inbox):
    from app import awaiting as aw
    first = aw.awaiting(now=NOW)["items"]
    ali = next(i for i in first if i["from_email"] == "ali@inconnu.ma")
    assert client.post("/api/mailbox/awaiting/dismiss", json={"items": [ali]}, headers=ORIGIN).json()["dismissed"] == 1
    assert {i["from_email"] for i in aw.awaiting(now=NOW, refresh=True)["items"]} == {"contact0@societe0.ma"}
    # un nouvel email d'Ali le fait revenir
    later = NOW - timedelta(days=5)
    inbox["imap"].deliver("INBOX", eml("Ali Inconnu <ali@inconnu.ma>", "Relance", later, "<b2@inconnu.ma>"), later.date())
    assert "ali@inconnu.ma" in {i["from_email"] for i in aw.awaiting(now=NOW, refresh=True)["items"]}
    client.post("/api/mailbox/awaiting/dismiss", json={"items": aw.awaiting(now=NOW)["items"]}, headers=ORIGIN)
    assert aw.awaiting(now=NOW)["items"] == []
    client.post("/api/mailbox/awaiting/restore", json={"senders": ["contact0@societe0.ma"]}, headers=ORIGIN)
    assert [i["from_email"] for i in aw.awaiting(now=NOW)["items"]] == ["contact0@societe0.ma"]


# ================================================================== V2.14

def test_placeholders_block_until_filled(client, world):  # noqa: F811
    from sqlalchemy import select

    from app import sequences_service as ss
    from app.db import get_session
    from app.models import Campaign, Contact, Sequence
    with get_session() as s:
        seq = s.get(Sequence, s.get(Campaign, world["campaign_id"]).sequence_id)
        st = ss.steps_of(s, seq)[0]
        st.body_template = "Bonjour,\\n\\nMerci d'émettre l'avenant sur la police [N° de police] au profit de [Banque]."
        s.commit()
        seq_id = seq.id
        cid = s.scalars(select(Contact)).first().id
    r = client.post(f"/api/sequences/{seq_id}/send", json={"contact_ids": [cid]}, headers=ORIGIN).json()
    assert r["refused"] and any("[N° de police]" in p and "[Banque]" in p for p in r["refused"][0]["problems"])
    pdf = client.post("/api/attachments", files={"file": ("carte_grise.pdf", b"%PDF-1.4 x", "application/pdf")}, headers=ORIGIN).json()
    ok = client.post(f"/api/sequences/{seq_id}/send", json={"contact_ids": [cid], "overrides": {"1": {
        "body": "Bonjour,\\n\\nMerci d'émettre l'avenant sur la police 123456 au profit de BMCE.", "attachment_ids": [pdf["id"]]}}},
        headers=ORIGIN).json()
    assert len(ok["sent"]) == 1
    from tests.test_m4_engine import START, _run
    _run(until=START + timedelta(days=21))
    raw = world["smtp"].messages[0].data
    assert b"carte_grise.pdf" in raw and "123456".encode() in raw


def test_mails_with_person(client, inbox):
    r = client.get("/api/mailbox/with?email=karim@client.ma").json()["items"]
    assert {(i["direction"], i["subject"]) for i in r} == {("in", "Sinistre"), ("out", "RE: Sinistre")}

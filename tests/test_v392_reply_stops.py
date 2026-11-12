"""V3.9.2 (12/11, Omar) : une réponse à un email de séquence arrête les relances de CE contact
seulement, quels que soient l'objet et l'adresse d'où la personne répond dans le fil."""
import random
from datetime import date, datetime, timedelta

from sqlalchemy import select

from app import engine, settings_store
from app.db import get_session
from app.mail import inbound
from app.models import Campaign, Contact, Enrollment, Message
from app.timeutil import TZ
from tests.conftest import USER
from tests.test_m4_engine import START, _activate, _run, world  # noqa: F401


def _mail(sender, subject, in_reply_to=None, body="Bonjour, oui ça m'intéresse, appelez-moi.", extra=""):
    thread = f"In-Reply-To: {in_reply_to}\r\nReferences: {in_reply_to}\r\n" if in_reply_to else ""
    return (f"From: {sender}\r\nTo: {USER}\r\nSubject: {subject}\r\nDate: Thu, 05 Nov 2026 10:00:00 +0000\r\n"
            f"Message-ID: <r{random.random()}@client.ma>\r\n{thread}{extra}"
            f"Content-Type: text/plain; charset=utf-8\r\n\r\n{body}\r\n").encode()


def test_reply_to_a_subject_about_leave_is_a_real_reply():
    a = inbound.analyse(_mail("k@client.ma", "RE: Vos salariés en congé : sont-ils couverts ?", "<x@oddo.ma>"))
    assert a.kind == "reply"
    a = inbound.analyse(_mail("k@client.ma", "Re : Absence de garantie incendie", "<x@oddo.ma>"))
    assert a.kind == "reply"
    # les vraies réponses automatiques restent reconnues
    assert inbound.analyse(_mail("k@client.ma", "Réponse automatique : Absent du bureau")).kind == "auto_reply"
    assert inbound.analyse(_mail("k@client.ma", "RE: Vos assurances", "<x@oddo.ma>",
                                 extra="Auto-Submitted: auto-replied\r\n")).kind == "auto_reply"


def test_only_the_contact_who_replied_stops_and_the_others_get_their_follow_up(world):  # noqa: F811
    with get_session() as s:
        settings_store.set_(s, "test_mode", False)
        s.commit()
    _activate(world["campaign_id"])
    _run(until=START + timedelta(hours=3))                      # 1er email aux 3 contacts
    first = {m.rcpt_tos[0] for m in world["smtp"].messages}
    assert first == {f"contact{i}@societe{i}.ma" for i in range(3)}
    with get_session() as s:
        sent = s.scalars(select(Message).where(Message.to_email == "contact0@societe0.ma")).one()
        subject, mid = sent.subject, sent.message_id
    # contact0 répond… depuis l'adresse de son assistante, dans le fil
    world["imap"].deliver("INBOX", _mail("Assistante <assistante@societe0.ma>", f"RE: {subject}", mid), when=date(2026, 11, 5))
    now = datetime(2026, 11, 9, 9, 0, tzinfo=TZ)
    for _ in range(80):                                         # jusqu'au bout de la séquence
        engine.tick(now=now, rng=random.Random(1), sync=True)
        now += timedelta(minutes=30)
    to = [m.rcpt_tos[0] for m in world["smtp"].messages]
    assert to.count("contact0@societe0.ma") == 1                # aucune relance pour celui qui a répondu
    assert to.count("contact1@societe1.ma") > 1 and to.count("contact2@societe2.ma") > 1  # les autres continuent
    with get_session() as s:
        c0 = s.scalars(select(Contact).where(Contact.email == "contact0@societe0.ma")).one()
        e0 = s.scalars(select(Enrollment).where(Enrollment.contact_id == c0.id)).one()
        assert (c0.global_status, e0.status, e0.stop_reason) == ("replied", "replied", "reply")
        others = s.scalars(select(Enrollment).where(Enrollment.contact_id != c0.id,
                                                    Enrollment.campaign_id == world["campaign_id"])).all()
        assert all(e.status != "replied" for e in others)
        assert s.get(Campaign, world["campaign_id"]).stop_on_domain_reply is False

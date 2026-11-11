"""V3.5.2 : un message partagé ou transféré n'est pas une réponse à la campagne."""
from sqlalchemy import func, select

from app import imap_sync
from app.db import get_session
from app.mailbox_service import get_primary
from app.models import Message
from tests.test_m4_engine import START, world  # noqa: F401
from tests.test_m5_imap import _contact, sent_world  # noqa: F401


def _eml(sender, subject, refs="", mid="<x@ext.ma>"):
    head = f"From: {sender}\r\nTo: o.douiri@oddo.ma\r\nSubject: {subject}\r\nDate: Wed, 04 Nov 2026 10:12:00 +0000\r\nMessage-ID: {mid}\r\n"
    if refs:
        head += f"In-Reply-To: {refs}\r\nReferences: {refs}\r\n"
    return (head + "MIME-Version: 1.0\r\nContent-Type: text/plain; charset=utf-8\r\n\r\nVoici le message.\r\n").encode()


def _process(raw):
    with get_session() as s:
        report = imap_sync.SyncReport()
        msg = imap_sync.process_raw(s, get_primary(s), raw, "INBOX", 1, report)
        s.commit()
        return (msg.id if msg else None), report.counts


def test_colleague_forwarding_a_prospect_reply_is_not_a_campaign_reply(sent_world):  # noqa: F811
    mid, counts = _process(_eml("Hamza <h.housni@oddo.ma>", "TR: Re: vos contrats", "<etape1-c0@oddo.ma>", "<f1@oddo.ma>"))
    assert mid is None and counts == {"internal": 1}
    assert _contact(0)[1].status == "waiting"  # la séquence continue


def test_colleague_message_is_not_matched_by_domain(sent_world):  # noqa: F811
    mid, counts = _process(_eml("j.jabrane@oddo.ma", "Point prospects de la semaine", mid="<f2@oddo.ma>"))
    assert mid is None


def test_external_forward_from_a_contact_does_not_stop_his_sequence(sent_world):  # noqa: F811
    mid, counts = _process(_eml("contact1@societe1.ma", "TR: Invitation salon", mid="<f3@societe1.ma>"))
    assert mid is None and counts == {"forward": 1}
    assert _contact(1)[1].status == "waiting"
    for subject in ("Fwd: brochure", "Fw: brochure", "Transf: brochure", "tr : brochure"):
        assert imap_sync.is_forward(subject)
    assert not imap_sync.is_forward("RE: TR: brochure") and not imap_sync.is_forward("Re: Transport et logistique")


def test_reply_in_a_forwarded_thread_still_counts(sent_world):  # noqa: F811
    mid, _ = _process(_eml("contact0@societe0.ma", "RE: TR: vos contrats", "<etape1-c0@oddo.ma>", "<f4@societe0.ma>"))
    assert mid is not None and _contact(0)[1].status == "replied"


def test_prospect_sending_back_our_email_still_counts(sent_world):  # noqa: F811
    mid, _ = _process(_eml("contact2@societe2.ma", "TR: Question rapide sur vos assurances", "<etape1-c2@oddo.ma>", "<f5@societe2.ma>"))
    assert mid is not None and _contact(2)[1].status == "replied"


def test_one_time_cleanup_of_existing_messages(sent_world):  # noqa: F811
    from app import starter_data
    c0, enr0 = _contact(0)
    with get_session() as s:
        s.add_all([
            Message(direction="in", kind="unmatched", subject="Point de la semaine", raw_headers="From: Hamza <h.housni@oddo.ma>\nTo: x",
                    received_at=START, message_id="<a@oddo.ma>"),
            Message(direction="in", kind="reply", contact_id=c0.id, subject="TR: brochure", raw_headers="From: contact0@societe0.ma",
                    received_at=START, message_id="<b@x>"),
            Message(direction="in", kind="reply", contact_id=c0.id, subject="Re: vos contrats", raw_headers="From: contact0@societe0.ma",
                    received_at=START, message_id="<c@x>"),
        ])
        s.commit()
        assert starter_data._cleanup_v352(s)["retires"] == 2
        s.commit()
        assert starter_data._cleanup_v352(s) == {"skipped": True}  # une seule fois
        assert s.scalar(select(func.count(Message.id)).where(Message.message_id == "<a@oddo.ma>")) == 0
        assert s.scalars(select(Message).where(Message.message_id == "<b@x>")).one().seen_at is not None
        assert s.scalars(select(Message).where(Message.message_id == "<c@x>")).one().seen_at is None

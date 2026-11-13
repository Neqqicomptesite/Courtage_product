"""V3.11.2 (13/11) : « Domain oddo.ma has exceeded the max defers and failures per hour (16/10 (25%))
allowed. Message discarded. » : l'hébergeur jette les emails quand trop échouent dans l'heure."""
import random
from datetime import datetime, timedelta

from sqlalchemy import select

from app import campaigns_service as camp_svc
from app import engine, imap_sync, sending_guard, settings_store
from app.db import get_session
from app.mail import inbound
from app.mailbox_service import get_primary
from app.models import Campaign, Contact, Enrollment, Message
from tests.conftest import USER
from tests.test_m4_engine import START, _activate, _run, world  # noqa: F401

LIMIT = ("From: Mail Delivery System <Mailer-Daemon@oddo.ma>\r\nTo: {user}\r\nSubject: Mail delivery failed: returning message to sender\r\n"
         "Date: {date}\r\nMessage-ID: <lim{n}@oddo.ma>\r\nContent-Type: text/plain; charset=utf-8\r\n\r\n"
         "This message was created automatically by mail delivery software.\r\n\r\n"
         "A message that you sent could not be delivered to one or more of its\r\nrecipients. This is a permanent error. The following address(es) failed:\r\n\r\n"
         "  {to}\r\n    Domain oddo.ma has exceeded the max defers and failures per hour (16/10 (25%)) allowed.  Message discarded.\r\n\r\n"
         "------ This is a copy of the message, including all the headers. ------\r\nMessage-ID: {mid}\r\nSubject: Re: offre\r\n")


def _limit(to, mid, when, n=1):
    return LIMIT.format(user=USER, date=when.strftime("%a, %d %b %Y %H:%M:%S +0000"), n=n, to=to, mid=mid).encode()


def test_provider_limit_is_recognised_and_not_a_bad_address():
    a = inbound.analyse(_limit("x@hotmail.fr", "<m1@oddo.ma>", START))
    assert a.sender_limit and a.kind == "bounce_soft" and "<m1@oddo.ma>" in a.referenced_ids


def test_discarded_email_is_resent_after_a_one_hour_pause(world):  # noqa: F811
    with get_session() as s:
        settings_store.set_(s, "test_mode", False)
        s.commit()
    _activate(world["campaign_id"])
    _run(until=START + timedelta(hours=3))
    with get_session() as s:
        first = s.scalars(select(Message).where(Message.direction == "out").order_by(Message.id)).first()
        to, mid, when, cid = first.to_email, first.message_id, first.sent_at, first.contact_id
    bounce_at = when + timedelta(minutes=10)
    with get_session() as s:
        imap_sync.process_raw(s, get_primary(s), _limit(to, mid, bounce_at), "INBOX", 99, imap_sync.SyncReport())
        s.commit()
        c = s.get(Contact, cid)
        enr = s.scalars(select(Enrollment).where(Enrollment.contact_id == cid)).one()
        assert c.global_status == "active"                       # l'adresse n'est pas en cause
        assert (enr.current_step, enr.next_due_at) == (1, bounce_at + sending_guard.PAUSE)
        assert "jeté" in settings_store.get(s, "engine_last_error")
    r = engine.tick(now=bounce_at + timedelta(minutes=5), rng=random.Random(1), sync=False)
    assert r.action == "paused"
    _run(until=START + timedelta(days=1), now=bounce_at + sending_guard.PAUSE)
    with get_session() as s:
        again = s.scalars(select(Message).where(Message.direction == "out", Message.contact_id == cid,
                                                Message.step_position == 1)).all()
        assert len(again) == 2                                   # l'email jeté est reparti


def test_three_bounces_in_an_hour_pause_sending(world):  # noqa: F811
    _activate(world["campaign_id"])
    now = START + timedelta(hours=2)
    with get_session() as s:
        for i in range(3):
            s.add(Message(direction="in", kind="bounce_hard", received_at=now - timedelta(minutes=10 * i),
                          test_mode=False, subject="Undelivered", message_id=f"<b{i}@x>"))
        s.commit()
    r = engine.tick(now=now, rng=random.Random(1), sync=False)
    assert r.action == "paused" and "rebonds" in r.detail
    with get_session() as s:
        assert sending_guard.paused_until(s) == now + sending_guard.PAUSE
    later = engine.tick(now=now + sending_guard.PAUSE + timedelta(minutes=1), rng=random.Random(1), sync=False)
    assert later.action != "paused"


def test_doubtful_emails_are_shown_and_can_be_excluded(world):  # noqa: F811
    with get_session() as s:
        c = s.scalars(select(Contact).order_by(Contact.id)).first()
        c.email_reliability = "À vérifier"
        s.commit()
        camp = s.get(Campaign, world["campaign_id"])
        r = camp_svc.activation_report(s, camp, include_overlapping=True)
        assert [x.contact.id for x in r.doubtful] == [c.id] and c.id in [x.contact.id for x in r.eligible]
        r2 = camp_svc.activation_report(s, camp, include_overlapping=True, include_doubtful=False)
        assert c.id not in [x.contact.id for x in r2.eligible] and len(r2.eligible) == len(r.eligible) - 1
        n = camp_svc.activate(s, camp, include_overlapping=True, include_doubtful=False, now=START)
        s.commit()
        assert n == len(r.eligible) - 1


def test_bounce_from_our_own_server_is_not_a_colleague():
    team = ({"o.douiri@oddo.ma"}, {"oddo.ma"})
    assert not imap_sync.is_internal("mailer-daemon@oddo.ma", team)
    assert not imap_sync.is_internal("postmaster@oddo.ma", team)
    assert imap_sync.is_internal("jihane@oddo.ma", team)

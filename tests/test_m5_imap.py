"""M5 : analyse des emails reçus, synchronisation IMAP et effets sur les séquences."""
from datetime import date, timedelta
from pathlib import Path

import pytest
from sqlalchemy import select

from app import imap_sync, settings_store, suppression
from app.db import get_session
from app.mail import inbound
from app.mailbox_service import get_primary
from app.models import Campaign, Contact, Enrollment, Message
from tests.conftest import USER
from tests.test_m4_engine import START, _activate, _run, world  # noqa: F401 (fixture réutilisée)

EML = Path(__file__).parent / "fixtures" / "eml"
ORIGIN = {"Origin": "http://testserver"}


def raw(name: str) -> bytes:
    return (EML / name).read_bytes()


# ------------------------------------------------------- 1. analyse pure (§12)

@pytest.mark.parametrize("name, kind", [
    ("01_reponse_avec_citation.eml", "reply"),
    ("02_reponse_collegue_meme_domaine.eml", "reply"),
    ("03_absence_fr.eml", "auto_reply"),
    ("04_absence_en.eml", "auto_reply"),
    ("05_rebond_definitif_511.eml", "bounce_hard"),
    ("06_rebond_temporaire_422.eml", "bounce_soft"),
    ("07_stop.eml", "unsubscribe"),
    ("09_reponse_html_seulement.eml", "reply"),
    ("10_reponse_sans_entete_de_fil.eml", "reply"),
])
def test_classification(name, kind):
    assert inbound.analyse(raw(name)).kind == kind


def test_quote_removed_and_full_text_kept():
    a = inbound.analyse(raw("01_reponse_avec_citation.eml"))
    assert a.text.endswith("Prénom0")
    assert "revue gratuite" not in a.text and "revue gratuite" in a.full_text


def test_html_only_reply_is_converted():
    a = inbound.analyse(raw("09_reponse_html_seulement.eml"))
    assert a.text == "Bonjour,\nEnvoyez-moi plutôt une proposition écrite.\nMerci"


def test_return_dates():
    assert inbound.analyse(raw("03_absence_fr.eml")).return_date == "12/11/2026"
    assert inbound.analyse(raw("04_absence_en.eml")).return_date == "November 12, 2026"
    assert inbound.return_date("Je serai de retour le 3 décembre.") == "3 décembre"


def test_bounce_details():
    b = inbound.analyse(raw("05_rebond_definitif_511.eml")).bounce
    assert (b.hard, b.status, b.recipient, b.original_message_id) == \
        (True, "5.1.1", "contact1@societe1.ma", "<etape1-c1@oddo.ma>")


@pytest.mark.parametrize("subject, body, expected", [
    ("Re: offre", "STOP", True),
    ("Re: offre", "stop merci", True),
    ("STOP", "", True),
    ("Re: offre", "Merci de me désinscrire", True),
    ("Re: offre", "Je ne souhaite plus recevoir vos messages", True),
    ("Re: offre", "Pouvons-nous faire un stop sur ce dossier et en reparler en janvier quand le budget sera voté ?", False),
    ("Re: offre", "Bonjour, oui intéressé.", False),
])
def test_unsubscribe_detection(subject, body, expected):
    assert inbound._is_unsubscribe(subject, body) is expected


def test_wrote_line_requires_colon():
    assert inbound.strip_quote("Le client a écrit hier.\nSuite") == "Le client a écrit hier.\nSuite"


def test_free_mail_domains():
    assert inbound.is_free_mail("gmail.com") and inbound.is_free_mail("hotmail.fr") and inbound.is_free_mail("outlook.com")
    assert not inbound.is_free_mail("societe0.ma")


# ------------------------------------------- 2. effets en base (process_raw)

def _fake_sent(test_mode=False):
    """Étape 1 « partie » pour les 3 contacts, avec des Message-ID connus des fichiers .eml."""
    with get_session() as s:
        for enr in s.scalars(select(Enrollment).order_by(Enrollment.id)):
            i = enr.contact_id - 1
            s.add(Message(enrollment_id=enr.id, contact_id=enr.contact_id, direction="out",
                          message_id=f"<etape1-c{i}@oddo.ma>", subject="Question rapide sur vos assurances",
                          sent_at=START, step_position=1, test_mode=test_mode,
                          to_email=USER if test_mode else f"contact{i}@societe{i}.ma"))
            enr.status, enr.current_step, enr.next_due_at = "waiting", 2, START + timedelta(days=6)
        s.commit()


def _process(name):
    with get_session() as s:
        report = imap_sync.SyncReport()
        msg = imap_sync.process_raw(s, get_primary(s), raw(name), "INBOX", 1, report)
        s.commit()
        return (msg.id if msg else None), report


def _contact(i):
    with get_session() as s:
        c = s.scalars(select(Contact).where(Contact.email == f"contact{i}@societe{i}.ma")).one()
        enr = s.scalars(select(Enrollment).where(Enrollment.contact_id == c.id)).one()
        return c, enr


@pytest.fixture
def sent_world(world):  # noqa: F811
    with get_session() as s:
        settings_store.set_(s, "test_mode", False)
        s.commit()
    _activate(world["campaign_id"])
    _fake_sent()
    return world


def test_reply_stops_sequence_and_marks_contact(sent_world):
    mid, _ = _process("01_reponse_avec_citation.eml")
    c, enr = _contact(0)
    assert (c.global_status, enr.status, enr.stop_reason, enr.next_due_at) == ("replied", "replied", "reply", None)
    with get_session() as s:
        m = s.get(Message, mid)
        assert (m.kind, m.classification, m.contact_id) == ("reply", None, c.id)
        assert "revue gratuite" not in m.body_text


def test_out_of_office_continues_and_shows_return_date(sent_world):
    mid, _ = _process("03_absence_fr.eml")
    c, enr = _contact(1)
    assert (c.global_status, enr.status) == ("active", "waiting")
    with get_session() as s:
        m = s.get(Message, mid)
        assert (m.kind, m.classification, m.return_date) == ("auto_reply", "out_of_office", "12/11/2026")


def test_out_of_office_can_stop_if_setting_off(sent_world):
    with get_session() as s:
        settings_store.set_(s, "auto_reply_continues", False)
        s.commit()
    _process("04_absence_en.eml")
    assert _contact(2)[1].status == "stopped"


def test_hard_bounce_marks_bounced(sent_world):
    _process("05_rebond_definitif_511.eml")
    c, enr = _contact(1)
    assert (c.global_status, enr.status) == ("bounced", "bounced")


def test_soft_bounce_changes_nothing(sent_world):
    _process("06_rebond_temporaire_422.eml")
    c, enr = _contact(2)
    assert (c.global_status, enr.status) == ("active", "waiting")


def test_stop_unsubscribes_and_feeds_exclusion_list(sent_world):
    _process("07_stop.eml")
    c, enr = _contact(0)
    assert (c.global_status, enr.status) == ("unsubscribed", "unsubscribed")
    with get_session() as s:
        assert suppression.is_suppressed_db(s, "contact0@societe0.ma")


def test_unrelated_email_is_not_stored(sent_world):
    mid, report = _process("08_sans_rapport.eml")
    assert mid is None and report.counts == {"unrelated": 1}


def test_colleague_reply_is_unmatched_then_attached(sent_world):
    mid, _ = _process("02_reponse_collegue_meme_domaine.eml")
    c, enr = _contact(0)
    assert enr.status == "waiting"  # rien n'est arrêté sans confirmation
    with get_session() as s:
        m = s.get(Message, mid)
        assert (m.kind, m.contact_id, m.suggested_contact_id) == ("unmatched", None, c.id)
    assert imap_sync.attach(mid, c.id)
    c, enr = _contact(0)
    assert (c.global_status, enr.status) == ("replied", "replied")


def test_reply_matched_by_sender_address(sent_world):
    _process("10_reponse_sans_entete_de_fil.eml")
    assert _contact(1)[1].status == "replied"


def test_same_message_twice_is_ignored(sent_world):
    _process("01_reponse_avec_citation.eml")
    mid, report = _process("01_reponse_avec_citation.eml")
    assert mid is None and report.counts == {"already_seen": 1}


def test_test_mode_reply_stops_sequence_but_keeps_contact_status(world):  # noqa: F811
    _activate(world["campaign_id"])
    _fake_sent(test_mode=True)
    _process("07_stop.eml")
    c, enr = _contact(0)
    assert enr.status == "unsubscribed"
    assert c.global_status == "active"  # §4 : en mode test, aucun statut de contact modifié
    with get_session() as s:
        assert not suppression.is_suppressed_db(s, c.email)


def test_stop_on_domain_reply_option(sent_world):
    with get_session() as s:
        camp = s.get(Campaign, sent_world["campaign_id"])
        camp.stop_on_domain_reply = True
        colleague = Contact(email="autre@societe0.ma", company="Société 0", sequence_code="FIN-IND")
        s.add(colleague)
        s.flush()
        s.add(Enrollment(campaign_id=camp.id, contact_id=colleague.id, status="waiting", current_step=2,
                         next_due_at=START + timedelta(days=6)))
        s.commit()
    _process("01_reponse_avec_citation.eml")
    with get_session() as s:
        other = s.scalars(select(Enrollment).join(Contact).where(Contact.email == "autre@societe0.ma")).one()
        assert (other.status, other.stop_reason) == ("stopped", "domain_reply")


# --------------------------------------------- 3. synchronisation IMAP réelle

def test_sync_reads_without_marking_seen_and_never_twice(sent_world):
    imap = sent_world["imap"]
    for n in ("01_reponse_avec_citation.eml", "03_absence_fr.eml", "08_sans_rapport.eml"):
        imap.deliver("INBOX", raw(n), when=date(2026, 11, 4))
    r1 = imap_sync.sync(now=START + timedelta(days=1))
    assert r1.ok and r1.counts == {"reply": 1, "auto_reply": 1, "unrelated": 1}
    # Rien n'a été marqué comme lu (BODY.PEEK) ni déplacé
    assert all("\\Seen" not in flags for _, flags, _ in imap.folders["INBOX"].messages)
    assert len(imap.folders["INBOX"].messages) == 3
    assert set(imap.commands) >= {"EXAMINE"} and "SELECT" not in imap.commands
    # Deuxième passage : rien de nouveau
    r2 = imap_sync.sync(now=START + timedelta(days=1, minutes=10))
    assert r2.counts == {}
    # Un nouveau message arrive : seul lui est lu
    imap.deliver("INBOX", raw("06_rebond_temporaire_422.eml"), when=date(2026, 11, 5))
    assert imap_sync.sync(now=START + timedelta(days=2)).counts == {"bounce_soft": 1}


def test_first_sync_skips_old_mailbox_history(sent_world):
    imap = sent_world["imap"]
    imap.deliver("INBOX", raw("10_reponse_sans_entete_de_fil.eml"), when=date(2025, 6, 1))  # avant tout envoi
    assert imap_sync.sync(now=START + timedelta(days=1)).counts == {}


def test_uidvalidity_change_does_not_duplicate(sent_world):
    imap = sent_world["imap"]
    imap.deliver("INBOX", raw("01_reponse_avec_citation.eml"), when=date(2026, 11, 4))
    imap_sync.sync(now=START + timedelta(days=1))
    imap.folders["INBOX"].uidvalidity = 99  # le serveur renumérote le dossier
    r = imap_sync.sync(now=START + timedelta(days=1, minutes=20))
    assert r.counts == {"already_seen": 1}
    with get_session() as s:
        assert len(list(s.scalars(select(Message).where(Message.direction == "in")))) == 1


def test_own_test_mode_emails_in_inbox_are_ignored(world):  # noqa: F811
    _activate(world["campaign_id"])
    _run(until=START + timedelta(hours=3))  # mode test : les 3 emails arrivent… chez Omar
    imap = world["imap"]
    for m in world["smtp"].messages:
        imap.deliver("INBOX", m.data, when=date(2026, 11, 3))
    r = imap_sync.sync(now=START + timedelta(hours=4))
    assert r.counts == {"ignored_own": 3}


def test_spam_folder_is_watched_too(sent_world):
    with get_session() as s:
        get_primary(s).watched_folders = ["INBOX", "INBOX.Junk"]
        s.commit()
    sent_world["imap"].deliver("INBOX.Junk", raw("07_stop.eml"), when=date(2026, 11, 4))
    assert imap_sync.sync(now=START + timedelta(days=1)).counts == {"unsubscribe": 1}


# ------------------------------------ 4. bout en bout (§12) et sûreté du moteur

def test_end_to_end_reply_prevents_step_2(client, world):  # noqa: F811
    """Import → campagne → envoi de l'étape 1 → réponse reçue → l'étape 2 ne part PAS."""
    from app import importer
    path = Path(__file__).parent / "fixtures" / "_e2e.csv"
    path.write_text("Email;Prénom;Entreprise;Code séquence\nnouveau@client-e2e.ma;Salma;Client E2E;FIN-IND\n",
                    encoding="utf-8")
    try:
        with get_session() as s:
            t = importer.read_table(path)
            importer.apply_plan(s, importer.plan_import(s, t, importer.auto_mapping(t.headers)), "e2e.csv")
            settings_store.set_(s, "test_mode", False)
            camp = s.get(Campaign, world["campaign_id"])
            camp.filters = {"sequence_code": "FIN-IND"}
            s.commit()
    finally:
        path.unlink()
    _activate(world["campaign_id"])
    _run(until=START + timedelta(hours=3))
    sent_to = [m.rcpt_tos[0] for m in world["smtp"].messages]
    assert sorted(sent_to) == ["contact0@societe0.ma", "nouveau@client-e2e.ma"]

    # Salma répond à l'email reçu
    with get_session() as s:
        first = s.scalars(select(Message).where(Message.to_email == "nouveau@client-e2e.ma")).one()
        reply = (f"From: Salma <nouveau@client-e2e.ma>\r\nTo: {USER}\r\nSubject: Re: {first.subject}\r\n"
                 f"Date: Thu, 05 Nov 2026 10:00:00 +0000\r\nMessage-ID: <rep-salma@client-e2e.ma>\r\n"
                 f"In-Reply-To: {first.message_id}\r\nReferences: {first.message_id}\r\n"
                 f"Content-Type: text/plain; charset=utf-8\r\n\r\nOui, appelez-moi.\r\n").encode()
    world["imap"].deliver("INBOX", reply, when=date(2026, 11, 5))

    # Le moteur tourne avec la synchro réelle (sync=True) jusqu'à la fin de la séquence
    from app import engine
    import random
    from app.timeutil import TZ
    from datetime import datetime
    now = datetime(2026, 11, 9, 9, 0, tzinfo=TZ)
    for _ in range(40):
        engine.tick(now=now, rng=random.Random(1), sync=True)
        now += timedelta(minutes=5)
    sent_to = [m.rcpt_tos[0] for m in world["smtp"].messages]
    assert sent_to.count("nouveau@client-e2e.ma") == 1   # étape 2 NON envoyée
    assert sent_to.count("contact0@societe0.ma") == 2    # l'autre contact a bien reçu sa relance
    with get_session() as s:
        salma = s.scalars(select(Contact).where(Contact.email == "nouveau@client-e2e.ma")).one()
        assert salma.global_status == "replied"


def test_engine_does_not_send_when_inbox_unreadable(world):  # noqa: F811
    from app import engine
    _activate(world["campaign_id"])
    world["imap"].stop()  # boîte injoignable
    r = engine.tick(now=START + timedelta(hours=2), sync=True)
    assert r.action == "sync_failed"
    assert world["smtp"].messages == []
    with get_session() as s:
        assert settings_store.get(s, "imap_last_error")


def test_imap_date_is_english_whatever_the_locale():
    assert imap_sync.imap_date(date(2026, 11, 3)) == "03-Nov-2026"
    assert imap_sync.imap_date(date(2027, 2, 14)) == "14-Feb-2027"


def test_dashboard_sync_button_and_unmatched(client, sent_world):
    sent_world["imap"].deliver("INBOX", raw("02_reponse_collegue_meme_domaine.eml"), when=date(2026, 11, 4))
    r = client.post("/sync", headers=ORIGIN)
    assert r.status_code == 200
    page = client.get("/classique").text
    assert "Réponse non rattachée" in page or "réponses non rattachées" in page.lower()
    assert "Société 0" in page

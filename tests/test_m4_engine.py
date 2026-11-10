"""M4 : campagnes et moteur d'envoi, avec horloge simulée et faux serveurs SMTP/IMAP.

Le test principal (critère d'acceptation M4) fait tourner le moteur sur deux
semaines simulées : 3 contacts × 3 étapes en mode test.
"""
import random
from datetime import datetime, timedelta, timezone
from email import message_from_bytes
from email.header import decode_header, make_header

import pytest
from sqlalchemy import func, select

from app import campaigns_service as camp_svc
from app import credentials, engine, settings_store
from app.db import get_session
from app.models import Campaign, ContentBlock, Contact, Enrollment, EventLog, Mailbox, Message, Sequence, Step
from app.scheduling import SendWindow
from app.timeutil import utcnow, TZ, to_local
from tests.conftest import PASSWORD, USER

UTC = timezone.utc
ORIGIN = {"Origin": "http://testserver"}
START = datetime(2026, 11, 3, 8, 0, tzinfo=TZ).astimezone(UTC)  # mardi 03/11/2026, 08:00 heure du Maroc


def _subject(raw: bytes) -> str:
    return str(make_header(decode_header(message_from_bytes(raw)["Subject"])))


@pytest.fixture
def world(db, smtp_ssl, imap_server):
    """Boîte configurée sur les faux serveurs, blocs et étapes rédigés, 3 contacts, campagne brouillon."""
    from app.seed import run_seed
    with get_session() as s:
        run_seed(s)
        s.add(Mailbox(display_name="Omar Douiri", email=USER, smtp_host="127.0.0.1", smtp_port=smtp_ssl.port,
                      smtp_security="ssl", imap_host="127.0.0.1", imap_port=imap_server.port, username=USER,
                      sent_folder="INBOX.Sent", signature="Omar Douiri\nODDO Assurance"))
        for b in s.scalars(select(ContentBlock)):
            b.body = f"Paragraphe {b.key} pour {{{{ entreprise }}}}."
        for st in s.scalars(select(Step)):
            st.body_template = st.body_template.replace("À RÉDIGER", "Texte")
        for i, code in enumerate(["FIN-IND", "RH-BTP", "DIR-SRV"]):
            s.add(Contact(email=f"contact{i}@societe{i}.ma", first_name=f"Prénom{i}", last_name="Test",
                          company=f"Société {i}", sequence_code=code, email_reliability="Bonne (test)"))
        s.flush()
        mb_id = s.scalars(select(Mailbox.id)).one()
        seq_id = s.scalars(select(Sequence.id)).first()
        camp = Campaign(name="Test M4", mailbox_id=mb_id, sequence_id=seq_id, filters={}, status="draft")
        s.add(camp)
        s.commit()
        camp_id = camp.id
    credentials.set_password(USER, PASSWORD)
    return {"smtp": smtp_ssl, "imap": imap_server, "campaign_id": camp_id}


def _activate(camp_id, now=START):
    with get_session() as s:
        n = camp_svc.activate(s, s.get(Campaign, camp_id), include_overlapping=False, now=now,
                              rng=random.Random(3))
        s.commit()
    return n


def _run(until: datetime, now: datetime = START, rng_seed=7, max_ticks=5000):
    """Fait tourner le moteur comme le planificateur (un passage par minute), en sautant
    directement aux moments utiles quand rien ne peut partir (nuit, week-end…)."""
    rng = random.Random(rng_seed)
    results = []
    for _ in range(max_ticks):
        if now >= until:
            break
        r = engine.tick(now=now, rng=rng, sync=False)
        results.append((now, r))
        with get_session() as s:
            window = SendWindow.from_settings(s)
            nb = settings_store.get(s, "engine_next_allowed_at")
            next_due = s.scalar(select(Enrollment.next_due_at).join(Campaign)
                                .where(Campaign.status == "active", Enrollment.status.in_(engine.DUE_STATUSES))
                                .order_by(Enrollment.next_due_at))
        if r.action == "gap" and nb:
            now = max(now + timedelta(minutes=1), datetime.fromisoformat(nb))
        elif r.action in ("closed", "cap_day", "cap_hour", "idle") and next_due:
            target = max(now + timedelta(minutes=1), next_due)
            now = window.next_open(target) if not window.is_open(target) else target
        elif r.action == "idle" and next_due is None:
            break
        else:
            now += timedelta(minutes=1)
    return results


def _sent_messages():
    with get_session() as s:
        return list(s.scalars(select(Message).where(Message.direction == "out", Message.sent_at.is_not(None))
                              .order_by(Message.sent_at)))


# ------------------------------------------------- critère d'acceptation M4

def test_acceptance_test_mode_3_contacts_3_steps(world):
    assert _activate(world["campaign_id"]) == 3
    _run(until=START + timedelta(days=21))

    smtp, imap = world["smtp"], world["imap"]
    # 1) 9 emails, TOUS chez Omar (mode test), objets préfixés
    assert len(smtp.messages) == 9
    assert all(m.rcpt_tos == [USER] for m in smtp.messages)
    subjects = [_subject(m.data) for m in smtp.messages]
    assert all(sub.startswith("[TEST → contact") for sub in subjects)

    sent = _sent_messages()
    assert len(sent) == 9 and all(m.test_mode and m.to_email == USER for m in sent)

    # 2) dans les fils : étapes 2 et 3 répondent à la précédente du même contact
    by_contact: dict[int, list[Message]] = {}
    for m in sent:
        by_contact.setdefault(m.contact_id, []).append(m)
    for msgs in by_contact.values():
        msgs.sort(key=lambda m: m.step_position)
        assert [m.step_position for m in msgs] == [1, 2, 3]
        assert msgs[1].in_reply_to == msgs[0].message_id
        assert msgs[2].in_reply_to == msgs[1].message_id
        assert msgs[2].references_header.split() == [msgs[0].message_id, msgs[1].message_id]
        assert msgs[1].subject == f"Re: {msgs[0].subject}"

    # 3) aux bonnes dates : J0 le 03/11, J+3 ouvrés en sautant le 06/11 (Marche Verte), J+7 ouvrés
    for msgs in by_contact.values():
        days = [to_local(m.sent_at).date().isoformat() for m in msgs]
        assert days == ["2026-11-03", "2026-11-09", "2026-11-13"], days

    # 4) fenêtres et délais entre deux envois
    with get_session() as s:
        window = SendWindow.from_settings(s)
        mb = s.scalars(select(Mailbox)).one()
    for m in sent:
        assert window.is_open(m.sent_at), to_local(m.sent_at)
    for a, b in zip(sent, sent[1:]):
        assert (b.sent_at - a.sent_at).total_seconds() >= mb.min_gap_s

    # 5) copie dans « Envoyés », marquée comme lue
    copies = imap.folders["INBOX.Sent"].messages
    assert len(copies) == 9 and all(flags == ["\\Seen"] for _, flags, _ in copies)

    # 6) campagne terminée, inscriptions « terminé sans réponse »
    with get_session() as s:
        assert s.get(Campaign, world["campaign_id"]).status == "finished"
        assert {e.status for e in s.scalars(select(Enrollment))} == {"completed"}


def test_ab_variants_assigned_at_activation(world):
    _activate(world["campaign_id"])
    with get_session() as s:
        labels = sorted(e.variant_label for e in s.scalars(select(Enrollment)))
    assert labels in (["A", "A", "B"], ["A", "B", "B"])


# --------------------------------------------------------------- plafonds

def test_daily_cap_spreads_sends_over_days(world):
    with get_session() as s:
        s.scalars(select(Mailbox)).one().daily_cap = 2
        s.commit()
    _activate(world["campaign_id"])
    _run(until=START + timedelta(days=2))
    days = [to_local(m.sent_at).date().isoformat() for m in _sent_messages()]
    assert days == ["2026-11-03", "2026-11-03", "2026-11-04"]


def test_hourly_cap(world):
    with get_session() as s:
        s.scalars(select(Mailbox)).one().hourly_cap = 1
        s.commit()
    _activate(world["campaign_id"])
    _run(until=START + timedelta(hours=10))
    sent = [m.sent_at for m in _sent_messages() if m.step_position == 1]
    assert len(sent) == 3
    for a, b in zip(sent, sent[1:]):
        assert b - a >= timedelta(hours=1)


def test_rampup_limits_first_days(world):
    with get_session() as s:
        settings_store.set_(s, "rampup_enabled", True)
        settings_store.set_(s, "rampup_per_day", 1)
        s.commit()
    _activate(world["campaign_id"])
    _run(until=START + timedelta(hours=12))
    assert len(_sent_messages()) == 1


def test_catch_up_after_pc_off_has_no_burst(world):
    """PC éteint 3 jours : au redémarrage, les envois en retard repartent un par un."""
    _activate(world["campaign_id"], now=START)
    restart = START + timedelta(days=3, hours=2)  # vendredi 06/11 férié -> lundi 09/11 09:00
    _run(until=datetime(2026, 11, 9, 12, 0, tzinfo=TZ).astimezone(UTC), now=restart)
    sent = _sent_messages()
    assert len(sent) == 3
    assert all(to_local(m.sent_at).date().isoformat() == "2026-11-09" for m in sent)
    for a, b in zip(sent, sent[1:]):
        assert (b.sent_at - a.sent_at).total_seconds() >= 90


# ------------------------------------------------------------------ sûreté

def test_test_mode_never_sends_to_contacts(world):
    _activate(world["campaign_id"])
    _run(until=START + timedelta(days=21))
    assert world["smtp"].messages and all(m.rcpt_tos == [USER] for m in world["smtp"].messages)
    for m in world["smtp"].messages:
        assert message_from_bytes(m.data)["To"] == USER


def test_real_mode_sends_to_contact(world):
    with get_session() as s:
        settings_store.set_(s, "test_mode", False)
        s.commit()
    _activate(world["campaign_id"])
    _run(until=START + timedelta(hours=3))
    rcpts = sorted(m.rcpt_tos[0] for m in world["smtp"].messages)
    assert rcpts == ["contact0@societe0.ma", "contact1@societe1.ma", "contact2@societe2.ma"]
    assert not any(_subject(m.data).startswith("[TEST") for m in world["smtp"].messages)


def test_interrupted_send_goes_to_review_and_is_never_resent(world):
    _activate(world["campaign_id"])
    # Simule une coupure pendant l'envoi : message enregistré, statut « sending », puis plus rien.
    with get_session() as s:
        enr = s.scalars(select(Enrollment).order_by(Enrollment.id)).first()
        enr.status, enr.updated_at = "sending", START
        s.add(Message(enrollment_id=enr.id, contact_id=enr.contact_id, direction="out",
                      message_id="<coupure@oddo.ma>", subject="x", step_position=1))
        s.commit()
        eid = enr.id
    _run(until=START + timedelta(hours=4))
    with get_session() as s:
        assert s.get(Enrollment, eid).status == "needs_review"
    assert len(world["smtp"].messages) == 2  # les 2 autres contacts seulement
    # L'utilisateur constate l'email dans ses Envoyés et valide : la séquence reprend à l'étape 2.
    assert engine.confirm_sent(eid, now=START + timedelta(hours=4))
    with get_session() as s:
        enr = s.get(Enrollment, eid)
        assert (enr.status, enr.current_step) == ("waiting", 2)


def test_retry_after_review_resends(world):
    _activate(world["campaign_id"])
    with get_session() as s:
        enr = s.scalars(select(Enrollment).order_by(Enrollment.id)).first()
        enr.status = "needs_review"
        s.commit()
        eid = enr.id
    assert engine.retry_now(eid, now=START + timedelta(hours=1, minutes=30))
    _run(until=START + timedelta(hours=4), now=START + timedelta(hours=1, minutes=30))
    with get_session() as s:
        assert s.get(Enrollment, eid).current_step == 2


def test_recheck_before_send_respects_status_and_exclusions(world):
    from app import suppression
    _activate(world["campaign_id"])
    with get_session() as s:
        c0, c1, _ = s.scalars(select(Contact).order_by(Contact.id)).all()
        c0.global_status = "do_not_contact"
        suppression.add(s, f"@{c1.email.split('@')[1]}", "Ajout manuel")
        s.commit()
    _run(until=START + timedelta(hours=3))
    assert len(world["smtp"].messages) == 1
    with get_session() as s:
        statuses = sorted(e.status for e in s.scalars(select(Enrollment)))
    assert statuses == ["stopped", "stopped", "waiting"]


def test_reply_received_stops_next_steps(world):
    _activate(world["campaign_id"])
    _run(until=START + timedelta(hours=3))
    with get_session() as s:
        c0 = s.scalars(select(Contact).order_by(Contact.id)).first()
        # Reçue APRÈS l'inscription (créée à l'heure réelle) : avec START + 1 jour, le test
        # échouait dès que la vraie date dépassait le 04/11/2026 08:00.
        s.add(Message(contact_id=c0.id, direction="in", kind="reply", subject="Re: …",
                      received_at=max(START + timedelta(days=1), utcnow())))
        s.commit()
    _run(until=START + timedelta(days=21), now=START + timedelta(days=1))
    with get_session() as s:
        c0 = s.scalars(select(Contact).order_by(Contact.id)).first()
        n = len(list(s.scalars(select(Message).where(Message.contact_id == c0.id, Message.direction == "out",
                                                     Message.sent_at.is_not(None)))))
        assert n == 1  # étape 1 seulement
    assert len(world["smtp"].messages) == 7


def test_pause_and_resume(world):
    _activate(world["campaign_id"])
    with get_session() as s:
        camp_svc.pause(s, s.get(Campaign, world["campaign_id"]))
        s.commit()
    _run(until=START + timedelta(hours=5))
    assert world["smtp"].messages == []
    with get_session() as s:
        camp_svc.resume(s, s.get(Campaign, world["campaign_id"]), now=START + timedelta(hours=5))
        s.commit()
    _run(until=START + timedelta(hours=7), now=START + timedelta(hours=5))
    assert len(world["smtp"].messages) == 3


# ------------------------------------------------------------ erreurs SMTP

def test_temporary_errors_retry_then_error(world):
    calls = {"n": 0}

    def failing_smtp(cfg):
        calls["n"] += 1
        raise ConnectionResetError("coupure réseau")

    _activate(world["campaign_id"])
    with get_session() as s:
        for e in s.scalars(select(Enrollment).order_by(Enrollment.id)).all()[1:]:
            e.status = "stopped"
        s.commit()
    now, delays = START + timedelta(hours=2), []
    for _ in range(4):
        r = engine.tick(now=now, smtp_factory=failing_smtp, sync=False)
        with get_session() as s:
            enr = s.scalars(select(Enrollment).order_by(Enrollment.id)).first()
            if enr.next_due_at:
                delays.append(round((enr.next_due_at - now).total_seconds() / 60))
                now = enr.next_due_at
    assert delays == [5, 15, 60]
    assert r.action == "failed"
    with get_session() as s:
        enr = s.scalars(select(Enrollment).order_by(Enrollment.id)).first()
        assert enr.status == "error" and "coupure réseau" in enr.last_error
        assert s.scalars(select(Message).where(Message.direction == "out")).first() is None


def test_permanent_recipient_refusal_is_hard_bounce(world):
    with get_session() as s:
        settings_store.set_(s, "test_mode", False)
        s.commit()
    world["smtp"].handler.reject_rcpt["contact0@societe0.ma"] = "550 5.1.1 Utilisateur inconnu"
    _activate(world["campaign_id"])
    _run(until=START + timedelta(hours=3))
    with get_session() as s:
        c0 = s.scalars(select(Contact).where(Contact.email == "contact0@societe0.ma")).one()
        assert c0.global_status == "bounced"
        enr = s.scalars(select(Enrollment).where(Enrollment.contact_id == c0.id)).one()
        assert enr.status == "bounced"
    assert len(world["smtp"].messages) == 2


def test_auth_error_suspends_without_losing_the_send(world):
    credentials.set_password(USER, "mauvais")
    _activate(world["campaign_id"])
    r = engine.tick(now=START + timedelta(hours=2), sync=False)
    assert r.action == "error"
    with get_session() as s:
        assert "mot de passe refusé" in settings_store.get(s, "engine_last_error")
        assert {e.status for e in s.scalars(select(Enrollment))} == {"scheduled"}
        assert s.scalars(select(Message).where(Message.direction == "out")).first() is None


def test_sent_copy_failure_does_not_block(world, monkeypatch):
    from app import sent_copy
    # le test simule le 03/11/2026, mais la règle « abandon après 7 jours » lit l'heure réelle
    monkeypatch.setattr(sent_copy, "MAX_AGE_S", 10 ** 10)
    with get_session() as s:
        s.scalars(select(Mailbox)).one().sent_folder = "Dossier inexistant"
        s.commit()
    _activate(world["campaign_id"])
    _run(until=START + timedelta(hours=3))
    assert len(world["smtp"].messages) == 3
    with get_session() as s:
        warnings = [e.text for e in s.scalars(select(EventLog).where(EventLog.level == "warning"))]
    assert any("Copie dans « Dossier inexistant » reportée" in w for w in warnings)
    # V2.20 : les copies attendent dans data/envoyes_a_copier et partent dès que c'est possible
    from app import sent_copy
    assert len(sent_copy.pending()) == 3
    imap = world["imap"]
    from tests.fakes.fake_imap import FakeFolder
    imap.folders["Dossier inexistant"] = FakeFolder(flags=[])
    from app import imap_sync
    assert imap_sync.sync(START + timedelta(hours=4)).ok
    assert sent_copy.pending() == [] and len(imap.folders["Dossier inexistant"].messages) == 3


# --------------------------------------------------------- activation (contrôles)

def test_activation_blocked_by_unresolved_variable(world):
    with get_session() as s:
        st = s.scalars(select(Step).where(Step.position == 1)).first()
        st.body_template += "\n{{ custom.inexistant }}"
        s.commit()
        report = camp_svc.activation_report(s, s.get(Campaign, world["campaign_id"]), False, now=START)
    assert report.blocked and len(report.with_problems) == 3
    with get_session() as s, pytest.raises(ValueError):
        camp_svc.activate(s, s.get(Campaign, world["campaign_id"]), False, now=START)


def test_activation_report_estimate_and_warnings(world):
    with get_session() as s:
        for c in s.scalars(select(Contact)):
            c.email_reliability = "Personnelle (Gmail)"
        s.commit()
        report = camp_svc.activation_report(s, s.get(Campaign, world["campaign_id"]), False, now=START)
    assert not report.blocked and len(report.eligible) == 3
    assert report.reliability_ratio == 1.0
    assert to_local(report.first_send).strftime("%d/%m %H:%M") == "03/11 09:00"
    assert to_local(report.last_send).date().isoformat() == "2026-11-13"


def test_contact_in_other_active_campaign_needs_force(world):
    _activate(world["campaign_id"])
    with get_session() as s:
        other = Campaign(name="Autre", mailbox_id=s.scalars(select(Mailbox.id)).one(),
                         sequence_id=s.scalars(select(Sequence.id)).first(), filters={}, status="draft")
        s.add(other)
        s.commit()
        oid = other.id
        assert len(camp_svc.activation_report(s, other, False, now=START).eligible) == 0
        assert len(camp_svc.activation_report(s, other, True, now=START).eligible) == 3


# --------------------------------------------------------------------- pages

def test_campaign_pages_flow(client, world):
    page = client.get("/campaigns").text
    assert "Test M4" in page and "Nouvelle campagne" in page
    r = client.post("/campaigns/new", data={"name": "Vague 1 FIN", "sequence_id": "1", "sequence_code": "FIN-IND"},
                    headers=ORIGIN)
    assert "1 contact(s) seront inscrits" in r.text
    cid = int(str(r.url).rstrip("/").rsplit("/", 1)[-1])
    confirm = client.get(f"/campaigns/{cid}/activate").text
    assert "Mode test activé" in confirm and "Activer en mode test" in confirm
    r = client.post(f"/campaigns/{cid}/activate", data={"confirm": "1"}, headers=ORIGIN)
    assert "Campagne activée : 1 contact(s)" in r.text
    r = client.post(f"/campaigns/{cid}/pause", headers=ORIGIN)
    assert "En pause" in r.text
    dash = client.get("/classique").text
    assert "Moteur d" in dash and "Envoyés aujourd" in dash


def test_delete_launched_campaign_keeps_sent_mails_and_daily_cap(world):
    """V3.4.3 : une campagne lancée peut être supprimée. Les envois prévus disparaissent ; les emails
    partis restent (fiche, boîte) et comptent toujours dans le plafond du jour de la boîte."""
    with get_session() as s:
        s.scalars(select(Mailbox)).one().daily_cap = 2
        s.commit()
    _activate(world["campaign_id"])
    _run(until=START + timedelta(hours=4))
    sent = _sent_messages()
    assert len(sent) == 2
    with get_session() as s:  # un message ancien (avant V3) n'avait pas de boîte : elle est retrouvée
        s.get(Message, sent[0].id).mailbox_id = None
        s.commit()
    now = START + timedelta(hours=4)
    with get_session() as s:
        mb = s.scalars(select(Mailbox)).one()
        assert engine.counters(s, mb, now)["today"] == 2
        camp = s.get(Campaign, world["campaign_id"])
        camp.status = "active"
        e = s.scalars(select(Enrollment).where(Enrollment.campaign_id == camp.id)).first()
        e.status = "sending"
        s.commit()
    with get_session() as s:  # un email en train de partir : on attend
        with pytest.raises(ValueError):
            camp_svc.delete(s, s.get(Campaign, world["campaign_id"]))
        s.rollback()
        s.scalars(select(Enrollment).where(Enrollment.status == "sending")).first().status = "waiting"
        s.commit()
    with get_session() as s:
        assert camp_svc.delete(s, s.get(Campaign, world["campaign_id"])) == 2
        s.commit()
    with get_session() as s:
        assert s.get(Campaign, world["campaign_id"]) is None
        assert s.scalar(select(func.count(Enrollment.id))) == 0
        kept = list(s.scalars(select(Message).where(Message.direction == "out")))
        assert len(kept) == 2 and all(m.enrollment_id is None and m.mailbox_id for m in kept)
        mb = s.scalars(select(Mailbox)).one()
        assert engine.counters(s, mb, now)["today"] == 2  # le plafond tient toujours
        assert any("supprimée" in ev.text for ev in s.scalars(select(EventLog)))


def test_delete_campaign_api(client, world):
    _activate(world["campaign_id"])
    r = client.post(f"/api/campaigns/{world['campaign_id']}/delete", headers=ORIGIN)
    assert r.status_code == 200 and r.json()["ok"]
    with get_session() as s:
        assert s.get(Campaign, world["campaign_id"]) is None

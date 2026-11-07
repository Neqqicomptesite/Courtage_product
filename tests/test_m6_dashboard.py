"""M6 : indicateurs, boîte Réponses, rappels, récapitulatif quotidien, export Excel.

Jeu de données connu (6 contacts, une campagne) :
  c0 FIN-IND A : étapes 1-2 envoyées, RÉPONSE classée « intéressé »   -> replied
  c1 FIN-IND B : étape 1, RÉPONSE non classée                         -> replied
  c2 RH-BTP  A : étapes 1-2-3, ABSENCE                                -> completed
  c3 RH-BTP  B : étape 1, REBOND définitif                            -> bounced
  c4 DIR-SRV A : étape 1, STOP                                        -> unsubscribed
  c5 DIR-SRV B : rien envoyé                                          -> scheduled
"""
import io
from datetime import date, datetime, timedelta, timezone
from email import message_from_bytes
from email.header import decode_header, make_header

import openpyxl
import pytest
from sqlalchemy import select

from app import BASE_URL, credentials, digest, settings_store, stats, suppression
from app.db import get_session
from app.models import Campaign, Contact, Enrollment, Mailbox, Message, Sequence
from app.timeutil import TZ
from tests.conftest import PASSWORD, USER

UTC = timezone.utc
ORIGIN = {"Origin": "http://testserver"}
DAY = datetime(2026, 11, 4, 10, 0, tzinfo=TZ).astimezone(UTC)  # mercredi 04/11/2026 10:00, heure du Maroc


@pytest.fixture
def dataset(db, smtp_ssl):
    from app.seed import run_seed
    with get_session() as s:
        run_seed(s)
        mb = Mailbox(display_name="Omar Douiri", email=USER, smtp_host="127.0.0.1", smtp_port=smtp_ssl.port,
                     smtp_security="ssl", imap_host="127.0.0.1", imap_port=993, username=USER)
        s.add(mb)
        s.flush()
        camp = Campaign(name="Vague 1", mailbox_id=mb.id, sequence_id=s.scalars(select(Sequence.id)).first(),
                        status="active", filters={})
        s.add(camp)
        s.flush()
        spec = [("FIN-IND", "A", 2, "reply", "interested", "replied"),
                ("FIN-IND", "B", 1, "reply", None, "replied"),
                ("RH-BTP", "A", 3, "auto_reply", "out_of_office", "completed"),
                ("RH-BTP", "B", 1, "bounce_hard", None, "bounced"),
                ("DIR-SRV", "A", 1, "unsubscribe", "unsubscribe", "unsubscribed"),
                ("DIR-SRV", "B", 0, None, None, "scheduled")]
        ids = []
        for i, (code, var, n_sent, kind, cls, status) in enumerate(spec):
            c = Contact(email=f"c{i}@entreprise{i}.ma", first_name=f"Prénom{i}", last_name="Test",
                        company=f"Entreprise {i}", sequence_code=code, phone=f"+212 522 00 00 0{i}")
            s.add(c)
            s.flush()
            e = Enrollment(campaign_id=camp.id, contact_id=c.id, variant_label=var, status=status,
                           current_step=n_sent + 1, next_due_at=DAY + timedelta(days=1) if status == "scheduled" else None)
            s.add(e)
            s.flush()
            for k in range(1, n_sent + 1):
                s.add(Message(enrollment_id=e.id, contact_id=c.id, direction="out", message_id=f"<s{i}{k}@oddo.ma>",
                              subject="Objet", sent_at=DAY - timedelta(days=3 - k), step_position=k, to_email=c.email))
            if kind:
                s.add(Message(enrollment_id=e.id, contact_id=c.id, direction="in", kind=kind, classification=cls,
                              subject=f"Re: Objet ({i})", body_text=f"Texte de la réponse {i}. " * 20,
                              received_at=DAY, message_id=f"<r{i}@entreprise{i}.ma>"))
            ids.append(c.id)
        s.commit()
        cid = camp.id
    credentials.set_password(USER, PASSWORD)
    return {"campaign_id": cid, "contact_ids": ids, "smtp": smtp_ssl}


# ----------------------------------------------------------------- indicateurs

def test_indicators_on_known_dataset(dataset):
    with get_session() as s:
        ind = stats.indicators(s, dataset["campaign_id"])
        assert (ind.enrolled, ind.reached) == (6, 5)
        assert ind.sent_by_step == {1: 5, 2: 2, 3: 1} and ind.sent_total == 8
        assert (ind.replies, ind.interested) == (2, 1)
        assert ind.reply_rate == pytest.approx(0.4)  # 2 réponses ÷ 5 contacts touchés
        assert (ind.bounced, ind.unsubscribed, ind.out_of_office, ind.completed_no_reply) == (1, 1, 1, 1)
        # global = la seule campagne
        assert stats.indicators(s).replies == 2


def test_segment_table(dataset):
    with get_session() as s:
        rows = {r.key: (r.reached, r.replies) for r in stats.by_segment(s, dataset["campaign_id"])}
    assert rows == {"DIR-SRV": (1, 0), "FIN-IND": (2, 2), "RH-BTP": (2, 0)}


def test_ab_table_and_small_sample_warning(dataset):
    with get_session() as s:
        rows, too_small = stats.ab_test(s, dataset["campaign_id"])
    assert {r.key: (r.reached, r.replies) for r in rows} == {"A": (3, 1), "B": (2, 1)}
    assert too_small is True


def test_dashboard_and_campaign_pages_show_indicators(client, dataset):
    page = client.get("/classique").text
    assert "40 % des 5 touchés" in page
    assert "Échantillon trop petit pour conclure avec certitude" in page
    assert "FIN-IND" in page and "File d" in page
    camp = client.get(f"/campaigns/{dataset['campaign_id']}").text
    assert "40 % des 5 touchés" in camp and f"/export?campaign_id={dataset['campaign_id']}" in camp


# ------------------------------------------------------------- boîte Réponses

def _msg_id(contact_index, dataset):
    with get_session() as s:
        return s.scalars(select(Message.id).where(Message.contact_id == dataset["contact_ids"][contact_index],
                                                  Message.direction == "in")).one()


def test_replies_inbox_default_filter_and_menu_counter(client, dataset):
    page = client.get("/replies").text
    assert "Prénom1" in page          # réponse non classée
    assert "Prénom0" not in page      # déjà classée « intéressé »
    assert '<span id="reply-count" class="count">1</span>' in page
    assert "Prénom0" in client.get("/replies?f=interested").text
    assert "Prénom2" in client.get("/replies?f=all").text  # absence visible dans « Toutes »


def test_one_click_classification_removes_card_and_updates_counter(client, dataset):
    mid = _msg_id(1, dataset)
    r = client.post(f"/replies/{mid}/classify", data={"c": "not_interested", "f": "unclassified"}, headers=ORIGIN)
    assert f'<div id="reply-{mid}"></div>' in r.text
    assert '<span id="reply-count" hx-swap-oob="true"></span>' in r.text
    with get_session() as s:
        assert s.get(Message, mid).classification == "not_interested"


def test_callback_requires_date_then_appears_in_reminders(client, dataset):
    mid = _msg_id(1, dataset)
    r = client.post(f"/replies/{mid}/classify", data={"c": "later", "f": "all"}, headers=ORIGIN)
    assert "Indiquez la date de rappel" in r.text
    today = date.today()
    r = client.post(f"/replies/{mid}/classify", data={"c": "later", "f": "all", "callback_on": today.isoformat()},
                    headers=ORIGIN)
    assert "À rappeler plus tard" in r.text and today.strftime("%d/%m/%Y") in r.text
    dash = client.get("/classique").text
    assert "Rappels du jour (1)" in dash and "+212 522 00 00 01" in dash
    client.post(f"/replies/{mid}/callback-done", headers=ORIGIN)
    assert "Rappels du jour" not in client.get("/classique").text


def test_note_is_saved(client, dataset):
    mid = _msg_id(1, dataset)
    r = client.post(f"/replies/{mid}/note", data={"note": "Demande devis flotte", "f": "all"}, headers=ORIGIN)
    assert "Demande devis flotte" in r.text


def test_manual_unsubscribe_and_wrong_contact_have_effects(client, dataset):
    client.post(f"/replies/{_msg_id(1, dataset)}/classify", data={"c": "unsubscribe"}, headers=ORIGIN)
    with get_session() as s:
        c1 = s.get(Contact, dataset["contact_ids"][1])
        assert c1.global_status == "unsubscribed" and suppression.is_suppressed_db(s, c1.email)
    client.post(f"/replies/{_msg_id(0, dataset)}/classify", data={"c": "wrong_contact"}, headers=ORIGIN)
    with get_session() as s:
        assert s.get(Contact, dataset["contact_ids"][0]).global_status == "do_not_contact"


# -------------------------------------------------------------- récapitulatif

def _at(hh, mm):
    return datetime(2026, 11, 4, hh, mm, tzinfo=TZ).astimezone(UTC)


def test_digest_sent_once_after_configured_time(dataset):
    smtp = dataset["smtp"]
    assert digest.maybe_send(now=_at(17, 59)) == "too_early"
    assert digest.maybe_send(now=_at(18, 1)) == "sent"
    assert digest.maybe_send(now=_at(18, 2)) == "already_sent"
    assert len(smtp.messages) == 1
    m = smtp.messages[0]
    assert m.rcpt_tos == [USER]
    parsed = message_from_bytes(m.data)
    subject = str(make_header(decode_header(parsed["Subject"])))
    assert subject == "[ODDO Séquences] Récap du 04/11 : 2 réponses"
    body = parsed.get_payload(decode=True).decode("utf-8")
    assert "Prénom0 Test – Entreprise 0 (FIN-IND)" in body
    assert "Rebond : c3@entreprise3.ma" in body and "Désinscription (STOP) : c4@entreprise4.ma" in body
    assert f"{BASE_URL}/v2/replies" in body
    excerpt = body.split("« ")[1].split(" »")[0]
    assert len(excerpt) <= 200
    assert parsed["List-Unsubscribe"] is None


def test_digest_not_counted_in_caps_and_skipped_without_activity(dataset):
    from app import engine
    with get_session() as s:
        mb = s.scalars(select(Mailbox)).one()
        before = engine.counters(s, mb, _at(18, 30))["today"]
    digest.maybe_send(now=_at(18, 1))
    with get_session() as s:
        assert engine.counters(s, mb, _at(18, 30))["today"] == before
    # Le lendemain sans aucune activité : rien n'est envoyé
    quiet = datetime(2026, 11, 7, 18, 5, tzinfo=TZ).astimezone(UTC)
    assert digest.maybe_send(now=quiet) == "no_activity"
    assert len(dataset["smtp"].messages) == 1


def test_digest_custom_recipient(dataset):
    with get_session() as s:
        settings_store.set_(s, "digest_recipient", "associe@oddo.ma")
        s.commit()
    digest.maybe_send(now=_at(18, 1))
    assert dataset["smtp"].messages[0].rcpt_tos == ["associe@oddo.ma"]


# ----------------------------------------------------------------------- export

def test_export_global_and_campaign_open_in_excel(client, dataset):
    for url in ("/export", f"/export?campaign_id={dataset['campaign_id']}"):
        r = client.get(url)
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("application/vnd.openxmlformats")
        assert "attachment" in r.headers["content-disposition"]
        wb = openpyxl.load_workbook(io.BytesIO(r.content))
        assert wb.sheetnames == ["Synthèse", "Contacts", "Réponses"]
        contacts = list(wb["Contacts"].iter_rows(values_only=True))
        assert len(contacts) == 1 + 6
        header = contacts[0]
        assert "Statut dans la campagne" in header and "Classement" in header
        synth = {row[0]: row[1] for row in wb["Synthèse"].iter_rows(values_only=True) if row and row[0]}
        assert synth["Réponses"] == 2 and synth["Taux de réponse"] == pytest.approx(0.4)
        assert synth["Emails envoyés – étape 1"] == 5
        assert "Échantillon trop petit pour conclure avec certitude" in synth
        replies = list(wb["Réponses"].iter_rows(values_only=True))
        assert len(replies) == 1 + 5
        dates = [row[4] for row in replies[1:]]
        assert all(isinstance(d, datetime) and d.tzinfo is None for d in dates)  # heure du Maroc, sans fuseau
        assert dates[0].hour == 10

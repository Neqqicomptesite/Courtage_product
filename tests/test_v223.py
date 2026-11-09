import pytest
"""V2.23 : gestion et souscription = un envoi par dossier. La même personne peut recevoir G1
plusieurs fois ; « A répondu » ne bloque que la prospection ; la contrainte (campagne, contact)
est retirée de la base sans rien perdre."""
import sqlite3
from email import message_from_bytes, policy
from datetime import timedelta

from sqlalchemy import select

from app import settings_store, starter_data
from app.db import get_session
from app.models import Contact, Enrollment, Message, Sequence
from app.paths import db_path
from tests.test_m4_engine import START, world  # noqa: F401

ORIGIN = {"Origin": "http://testserver"}
OV = {"1": {"subject": "Demande d'avenant – police 40.1 – Client A",
            "body": "Bonjour,\n\nAvenant pour la police 40.1, client A, ajout d'un véhicule au 01/12.\n\nBien cordialement,"}}


def _setup():
    with get_session() as s:
        starter_data.apply_sequences(s, force=True)
        g = Contact(email="gestion@compagnie.ma", first_name="Karima", kind="insurer")
        p = Contact(email="daf@prospect.ma", first_name="Hamza", kind="prospect", company="Prospect SA",
                    sequence_code="FIN-IND")
        s.add_all([g, p])
        s.commit()
        seq = {q.name[:2]: q.id for q in s.scalars(select(Sequence))}
        return g.id, p.id, seq


def test_same_gestion_sequence_twice_to_same_person(client, world):  # noqa: F811
    g, _, seq = _setup()
    for _ in range(2):
        r = client.post(f"/api/sequences/{seq['G1']}/send", json={"contact_ids": [g], "overrides": OV}, headers=ORIGIN).json()
        assert r["sent"] and not r["refused"], r
    with get_session() as s:
        assert len(list(s.scalars(select(Enrollment).where(Enrollment.contact_id == g)))) == 2
    # une autre séquence de gestion en parallèle : pas de question « déjà en cours ailleurs »
    r = client.post(f"/api/sequences/{seq['G5']}/send", json={"contact_ids": [g], "overrides": {"1": {
        "subject": "Demande d'attestation – police 40.1 – Client A", "body": "Bonjour,\n\nMerci de nous adresser l'attestation.\n"}}},
        headers=ORIGIN).json()
    assert r["sent"] and not r["refused"], r


def test_prospection_still_once(client, world):  # noqa: F811
    _, p, seq = _setup()
    assert client.post(f"/api/sequences/{seq['P2']}/send", json={"contact_ids": [p]}, headers=ORIGIN).json()["sent"]
    r = client.post(f"/api/sequences/{seq['P2']}/send", json={"contact_ids": [p]}, headers=ORIGIN).json()
    assert not r["sent"] and "déjà reçu" in r["refused"][0]["reason"]


def test_reply_from_insurer_keeps_status_active(client, world):  # noqa: F811
    from app import imap_sync
    g, p, _ = _setup()
    with get_session() as s:
        settings_store.set_(s, "test_mode", False)
        for cid in (g, p):
            m = Message(contact_id=cid, direction="in", kind="reply", subject="Re", received_at=START)
            s.add(m)
            s.flush()
            imap_sync.apply_effects(s, m, s.get(Contact, cid), test_mode=False, auto_reply_continues=True)
        s.commit()
        assert s.get(Contact, g).global_status == "active"     # gestionnaire : toujours joignable
        assert s.get(Contact, p).global_status == "replied"    # prospect : ne plus le prospecter


def test_replied_prospect_individual_yes_group_no(client, world):  # noqa: F811
    """« A répondu » : P2 envoyée à l'unité après le rendez-vous, oui ; une campagne de groupe de
    prospection, non ; une séquence de gestion, oui."""
    from app import campaigns_service as camp_svc
    from app.models import Campaign, Mailbox, Sequence
    _, p, seq = _setup()
    with get_session() as s:
        s.get(Contact, p).global_status = "replied"
        s.commit()
    assert client.post(f"/api/sequences/{seq['P2']}/send", json={"contact_ids": [p]}, headers=ORIGIN).json()["sent"]
    r = client.post(f"/api/sequences/{seq['G6']}/send", json={"contact_ids": [p], "overrides": {"1": {
        "subject": "Votre dossier flotte : documents à nous transmettre", "body": "Bonjour,\n\nIl nous manque la carte grise.\n"}}},
        headers=ORIGIN).json()
    assert r["sent"], r
    with get_session() as s:
        group = Campaign(name="Groupe P1", mailbox_id=s.scalars(select(Mailbox.id)).first(), sequence_id=seq["P1"],
                         status="draft", filters={})
        s.add(group); s.flush()
        cand = next(c for c in camp_svc.candidates(s, group, check_render=False) if c.contact.id == p)
        assert cand.excluded and "Statut" in cand.excluded
        s.rollback()


def test_second_avenant_is_really_sent(client, world):  # noqa: F811
    """Les deux dossiers partent bien, chacun avec son objet (le moteur, pas seulement l'inscription)."""
    from app import engine
    g, _, seq = _setup()
    ov2 = {"1": {"subject": "Demande d'avenant – police 77.2 – Client B", "body": OV["1"]["body"].replace("40.1", "77.2")}}
    client.post(f"/api/sequences/{seq['G1']}/send", json={"contact_ids": [g], "overrides": OV}, headers=ORIGIN)
    client.post(f"/api/sequences/{seq['G1']}/send", json={"contact_ids": [g], "overrides": ov2}, headers=ORIGIN)
    with get_session() as s:
        from app.scheduling import SendWindow
        window = SendWindow.from_settings(s)
        now = window.next_open(max(e.next_due_at for e in s.scalars(select(Enrollment))) + timedelta(minutes=1))
    log = []
    for _ in range(6):
        r = engine.tick(now=now, sync=False)
        log.append((now, r.action, r.message if hasattr(r, "message") else ""))
        now = window.next_open(now + timedelta(minutes=30))  # indépendant de l'heure du test
    from tests.test_m4_engine import _subject
    assert [a for _, a, _ in log].count("sent") == 2
    subjects = [_subject(x.data) for x in world["smtp"].messages]
    assert any("40.1" in x for x in subjects) and any("77.2" in x for x in subjects), subjects


@pytest.mark.sqlite_only
def test_unique_constraint_removed_from_database(db):
    con = sqlite3.connect(db_path())
    ddl = con.execute("SELECT sql FROM sqlite_master WHERE name='enrollment'").fetchone()[0]
    con.close()
    assert "UNIQUE" not in ddl.upper()


def _two_dossiers_sent(client, world):  # noqa: F811
    from app import engine
    from app.scheduling import SendWindow
    g, _, seq = _setup()
    ov2 = {"1": {"subject": "Demande d'avenant – police 77.2 – Client B", "body": OV["1"]["body"].replace("40.1", "77.2")}}
    client.post(f"/api/sequences/{seq['G1']}/send", json={"contact_ids": [g], "overrides": OV}, headers=ORIGIN)
    client.post(f"/api/sequences/{seq['G1']}/send", json={"contact_ids": [g], "overrides": ov2}, headers=ORIGIN)
    with get_session() as s:
        window = SendWindow.from_settings(s)
        now = window.next_open(max(e.next_due_at for e in s.scalars(select(Enrollment))) + timedelta(minutes=1))
    for _ in range(6):
        engine.tick(now=now, sync=False)
        now = window.next_open(now + timedelta(minutes=30))  # indépendant de l'heure du test
    with get_session() as s:
        out = {m.subject: (m.message_id, m.enrollment_id) for m in s.scalars(select(Message).where(Message.direction == "out"))}
    a = next(v for k, v in out.items() if "40.1" in k)
    b = next(v for k, v in out.items() if "77.2" in k)
    return g, a, b, now


def test_reply_to_one_dossier_keeps_the_other_running(client, world):  # noqa: F811
    from email.utils import format_datetime
    """Karima répond au dossier 40.1 : ses relances s'arrêtent, celles du dossier 77.2 continuent."""
    from app import imap_sync
    from tests.test_v24 import _eml
    g, (mid_a, enr_a), (_, enr_b), now = _two_dossiers_sent(client, world)
    raw = _eml("Karima <gestion@compagnie.ma>", "Re: avenant 40.1", "Bien reçu, en cours.", msgid="<rep-a@compagnie.ma>",
               in_reply_to=mid_a).replace(b"Wed, 04 Nov 2026 09:00:00 +0000", format_datetime(now).encode())
    world["imap"].deliver("INBOX", raw, now.date())  # reçue APRÈS l'envoi des deux dossiers
    imap_sync.sync(now=now)
    with get_session() as s:
        assert s.get(Enrollment, enr_a).status == "replied"
        assert s.get(Enrollment, enr_b).status in ("waiting", "scheduled")
        assert s.get(Contact, g).global_status == "active"
        due = s.get(Enrollment, enr_b).next_due_at
    # la relance 1 du dossier 77.2 part réellement
    from app import engine
    from app.scheduling import SendWindow
    with get_session() as s:
        t = SendWindow.from_settings(s).next_open(due + timedelta(minutes=1))
    for _ in range(4):
        engine.tick(now=t, sync=False)
        t += timedelta(minutes=30)
    with get_session() as s:
        sent_b = s.scalars(select(Message).where(Message.direction == "out", Message.enrollment_id == enr_b)).all()
        sent_a = s.scalars(select(Message).where(Message.direction == "out", Message.enrollment_id == enr_a)).all()
        assert (len(sent_a), len(sent_b)) == (1, 2)


def test_reply_without_thread_stops_all_dossiers(client, world):  # noqa: F811
    """Email écrit à part (sans citer nos emails) : on ne sait pas de quel dossier il parle -> tout s'arrête."""
    from app import imap_sync
    from tests.test_v24 import _eml
    g, (_, enr_a), (_, enr_b), now = _two_dossiers_sent(client, world)
    world["imap"].deliver("INBOX", _eml("Karima <gestion@compagnie.ma>", "Vos dossiers", "Je traite vos demandes.",
                                        msgid="<rep-x@compagnie.ma>"), now.date())
    imap_sync.sync(now=now)
    with get_session() as s:
        assert {s.get(Enrollment, enr_a).status, s.get(Enrollment, enr_b).status} == {"replied"}


def test_same_request_to_several_companies_fields_filled_once(client, world):  # noqa: F811
    """Cotation : S1 à 3 souscripteurs, les [champs] remplis une fois, chacun reçoit SON email."""
    from app import engine
    from app.scheduling import SendWindow
    _, _, seq = _setup()
    with get_session() as s:
        a = Contact(email="youssef@cie-a.ma", first_name="Youssef", kind="insurer", company="Cie A")
        b = Contact(email="samir@cie-b.ma", first_name="Samir", kind="insurer", company="Cie B")
        s.add_all([a, b]); s.commit()
        ids = [a.id, b.id]
    holes = client.get(f"/api/sequences/{seq['S1']}/holes").json()["holes"]
    assert {"Nom du client", "Risque à couvrir", "Activité", "Date d'effet"} <= set(holes)
    # sans les champs : refusé (email incomplet)
    r = client.post(f"/api/sequences/{seq['S1']}/send", json={"contact_ids": ids}, headers=ORIGIN).json()
    assert not r["sent"] and len(r["refused"]) == 2
    fills = {"Nom du client": "Nova Conseil", "Risque à couvrir": "RC professionnelle", "Activité": "conseil en gestion",
             "Date d'effet": "1er janvier 2027"}
    r = client.post(f"/api/sequences/{seq['S1']}/send", json={"contact_ids": ids, "fills": fills}, headers=ORIGIN).json()
    assert len(r["sent"]) == 2, r
    with get_session() as s:
        window = SendWindow.from_settings(s)
        now = window.next_open(max(e.next_due_at for e in s.scalars(select(Enrollment))) + timedelta(minutes=1))
    for _ in range(4):
        engine.tick(now=now, sync=False)
        now = window.next_open(now + timedelta(minutes=30))  # saute la pause de midi : test indépendant de l'heure
    with get_session() as s:
        out = {m.contact_id: m for m in s.scalars(select(Message).where(Message.direction == "out"))}
    assert set(out) == set(ids)
    for cid, name in zip(ids, ["Youssef", "Samir"]):
        assert out[cid].subject == "Demande de cotation – Nova Conseil – RC professionnelle"
    sent = [message_from_bytes(m.data, policy=policy.default) for m in world["smtp"].messages]
    bodies = [m.get_body(preferencelist=("plain",)).get_content() for m in sent]
    assert any("Bonjour Youssef" in t and "conseil en gestion" in t for t in bodies)
    assert any("Bonjour Samir" in t and "1er janvier 2027" in t for t in bodies)


def test_one_email_template_is_offered_in_modeles(client, db):
    """V2.23.1 : « Un seul email » crée un modèle d'une seule étape, que Modèles sait insérer."""
    r = client.post("/api/sequences", json={"name": "Cotation AT", "category": "souscription", "steps": 1}, headers=ORIGIN)
    sid = r.json()["id"]
    d = client.get(f"/api/sequences/{sid}").json()
    assert len(d["steps"]) == 1
    assert client.post("/api/sequences", json={"name": "X", "steps": 0}, headers=ORIGIN).status_code == 422
    assert len(client.get(f"/api/sequences/{client.post('/api/sequences', json={'name': 'Y'}, headers=ORIGIN).json()['id']}").json()["steps"]) == 3

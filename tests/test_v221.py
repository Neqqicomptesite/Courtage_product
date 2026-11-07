"""V2.21 : réponses rangées ou supprimées ailleurs quand même vues ; modèles dans « Nouveau
message » ; email sans objet permis (l'écran demande confirmation)."""
from datetime import timedelta
from email.message import EmailMessage

from sqlalchemy import select

from app import imap_sync
from app.db import get_session
from app.models import Contact, Enrollment, Message, Sequence
from tests.fakes.fake_imap import FakeFolder
from tests.test_m4_engine import START, _activate, _run, world  # noqa: F401

ORIGIN = {"Origin": "http://testserver"}


def _reply_to(msg: Message, sender: str) -> bytes:
    m = EmailMessage()
    m["From"], m["To"], m["Subject"] = sender, "omar@oddo.ma", "Re: " + (msg.subject or "")
    m["Message-ID"], m["In-Reply-To"], m["References"] = "<rep-archive@client.ma>", msg.message_id, msg.message_id
    m["Date"] = "Wed, 04 Nov 2026 20:00:00 +0000"
    m.set_content("Merci, rappelez-moi demain.")
    return m.as_bytes()


def test_reply_archived_on_phone_still_stops_sequence(world):  # noqa: F811
    imap = world["imap"]
    imap.folders["INBOX.Archive"] = FakeFolder(flags=["\\Archive"])
    imap.folders["INBOX.Trash"] = FakeFolder(flags=["\\Trash"])
    _activate(world["campaign_id"])
    _run(until=START + timedelta(hours=3))
    with get_session() as s:
        first = s.scalars(select(Message).where(Message.direction == "out").order_by(Message.id)).first()
        contact = s.get(Contact, first.contact_id)
        raw = _reply_to(first, contact.email)
    imap.deliver("INBOX.Archive", raw, (START + timedelta(hours=4)).date())   # rangée depuis le téléphone
    r = imap_sync.sync(START + timedelta(hours=5))
    assert r.ok, r.error
    with get_session() as s:
        enr = s.scalars(select(Enrollment).where(Enrollment.contact_id == contact.id)).one()
        assert enr.status == "replied"
    # relire une seconde fois (même email, autre dossier ou non) ne crée pas de doublon
    imap.deliver("INBOX.Trash", raw, (START + timedelta(hours=4)).date())
    imap_sync.sync(START + timedelta(hours=6))
    with get_session() as s:
        assert len(list(s.scalars(select(Message).where(Message.direction == "in")))) == 1


def test_missing_safety_folder_never_blocks_sync(world):  # noqa: F811
    assert imap_sync.sync(START).ok   # pas d'Archive ni de Corbeille : rien ne change


def test_template_for_known_and_unknown_recipient(client, world):  # noqa: F811
    with get_session() as s:
        seq_id = s.scalars(select(Sequence.id)).first()
    known = client.get(f"/api/sequences/{seq_id}/template", params={"email": "Contact0@societe0.ma"}).json()
    assert known["contact"]["email"] == "contact0@societe0.ma" and "Prénom0" in known["body"]
    unknown = client.get(f"/api/sequences/{seq_id}/template", params={"email": "x@y.ma"}).json()
    assert unknown["contact"] is None and "{{" not in unknown["body"] and "Madame, Monsieur" in unknown["body"]
    assert client.get(f"/api/sequences/{seq_id}/template", params={"position": 9}).status_code == 404


def test_send_without_subject_allowed(client, world):  # noqa: F811
    r = client.post("/api/mailbox/send", json={"to": "client@x.ma", "subject": "", "body": "Bonjour"}, headers=ORIGIN)
    assert r.status_code == 200, r.text
    assert world["smtp"].messages, "l'email est parti"


def test_guide_steps_stay_done(client, db):
    from app import settings_store
    with get_session() as s:
        settings_store.set_(s, "test_mode", False)
        s.commit()
    assert client.get("/api/guide").json()["steps"]["real"]
    with get_session() as s:
        settings_store.set_(s, "test_mode", True)   # retour en mode test
        s.commit()
    assert client.get("/api/guide").json()["steps"]["real"]   # l'étape reste faite


def test_guide_real_detected_from_past_real_send(client, db):
    with get_session() as s:
        s.add(Message(direction="out", test_mode=False, subject="x"))
        s.commit()
    assert client.get("/api/guide").json()["steps"]["real"]


def test_draft_relance_has_no_false_warning(client, db):
    from app import starter_data
    from app.seed import run_seed
    with get_session() as s:
        run_seed(s)
        starter_data.apply_sequences(s)
        c = Contact(email="k@compagnie.ma", first_name="Karima", kind="insurer")
        s.add(c)
        s.commit()
        g1 = s.scalars(select(Sequence).where(Sequence.name.like("G1%"))).one()
        ids = (g1.id, c.id)
    d = client.get(f"/api/sequences/{ids[0]}/draft", params={"contact_id": ids[1]}).json()
    assert d["steps"][0]["problems"]                     # le 1er email a des [champs]
    assert all(not s["problems"] for s in d["steps"][1:])  # les relances n'en ont pas

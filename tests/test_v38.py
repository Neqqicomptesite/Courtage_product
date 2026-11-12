"""V3.8 : confier une liste à un collègue (cloche + email) ; prochaine étape ; vos emails jamais
affichés comme ceux d'un prospect ; copie « Envoyés » jamais rangée dans la réception, file par boîte."""
from datetime import datetime, timezone
from types import SimpleNamespace

from sqlalchemy import select

from app import address_book, sent_copy
from app.db import get_session
from app.models import Contact, ContactList
from tests.test_v3_auth import H, _two_boxes, server  # noqa: F401
from tests.test_m4_engine import world  # noqa: F401


def test_assign_list_to_colleague_with_bell_and_email(server):  # noqa: F811
    _two_boxes()
    with get_session() as s:
        c = Contact(email="prospect@btp-demo.ma", first_name="Karim", last_name="Alaoui")
        s.add(c)
        s.commit()
        cid = c.id
    lid = server.post("/api/lists", json={"name": "BTP Casablanca", "contact_ids": [cid]}, headers=H("omar@oddo.ma")).json()["id"]
    team = server.get("/api/lists/colleagues", headers=H("omar@oddo.ma")).json()["items"]
    hamza = next(p for p in team if p["email"] == "hamza@oddo.ma")
    assert all(p["email"] != "omar@oddo.ma" for p in team) and all(p["email"] != "parti@oddo.ma" for p in team)
    # Hamza ne voit pas encore la liste perso d'Omar, et ne peut pas la confier
    assert all(x["id"] != lid for x in server.get("/api/lists", headers=H("hamza@oddo.ma")).json()["items"])
    r = server.post(f"/api/lists/{lid}/assign", headers=H("omar@oddo.ma"),
                    json={"user_id": hamza["id"], "note": "Bonjour Hamza,\nJe te confie la liste.", "email": True}).json()
    assert r["assigned_to"] == "Hamza" and r["owner"] == "Hamza" and r["assigned_by_me"] is True
    assert r["email_sent"] is False and r["email_error"]          # pas de mot de passe de boîte en test : la liste est confiée quand même
    mine = next(x for x in server.get("/api/lists", headers=H("hamza@oddo.ma")).json()["items"] if x["id"] == lid)
    assert mine["mine"] and mine["assigned_by"] == "Omar" and mine["editable"]
    still = next(x for x in server.get("/api/lists", headers=H("omar@oddo.ma")).json()["items"] if x["id"] == lid)
    assert still["assigned_by_me"] and not still["mine"]          # Omar la garde en vue
    bell = server.get("/api/notifications", headers=H("hamza@oddo.ma")).json()["items"]
    n = next(i for i in bell if i["type"] == "list")
    assert "Omar vous a confié 1 contact" in n["title"] and n["href"] == f"/campaigns/new?list_id={lid}"
    assert not [i for i in server.get("/api/notifications", headers=H("omar@oddo.ma")).json()["items"] if i["type"] == "list"]
    # Hamza ne peut pas la « re-confier » à lui-même ; un inconnu est refusé
    assert server.post(f"/api/lists/{lid}/assign", headers=H("hamza@oddo.ma"), json={"user_id": hamza["id"], "email": False}).status_code == 422
    assert server.post(f"/api/lists/{lid}/assign", headers=H("hamza@oddo.ma"), json={"user_id": 999, "email": False}).status_code == 422


def test_next_step_follows_the_nine_steps(server):  # noqa: F811
    _two_boxes()
    d = server.get("/api/me/next-step", headers=H("hamza@oddo.ma")).json()
    assert d["total"] == 9 and len(d["steps"]) == 9 and d["next"]["key"] == next(x["key"] for x in d["steps"] if not x["done"])


def test_own_address_never_a_prospect_nor_a_suggestion(client, world):  # noqa: F811
    with get_session() as s:
        from app.models import Mailbox
        me = s.scalars(select(Mailbox)).first().email
        if not s.scalars(select(Contact).where(Contact.email == me)).first():
            s.add(Contact(email=me, first_name="Omar", last_name="Douiri"))
        s.commit()
        assert me in address_book._own_addresses(s)
        assert me not in [i["email"] for i in address_book.suggest(s, me[:4])]
    from app.web.api_mailbox import _people
    assert me not in _people({me})


def test_sent_copy_never_in_inbox_and_queue_per_mailbox(tmp_path, monkeypatch):
    monkeypatch.setattr(sent_copy, "data_dir", lambda: tmp_path)
    assert sent_copy.safe_folder("INBOX") is None and sent_copy.safe_folder(" inbox ") is None
    assert sent_copy.safe_folder("INBOX.Sent") == "INBOX.Sent"
    calls = []
    err = sent_copy.copy_or_queue(SimpleNamespace(username="a@x.ma"), "INBOX", b"x", datetime.now(timezone.utc), lambda c: calls.append(c))
    assert err and not calls                                       # rien n'est copié dans la réception
    boom = lambda cfg: (_ for _ in ()).throw(OSError("coupure"))   # noqa: E731
    now = datetime.now(timezone.utc)
    sent_copy.copy_or_queue(SimpleNamespace(username="a@x.ma"), "Sent", b"From: a@x.ma\r\n\r\nA", now, boom)
    sent_copy.copy_or_queue(SimpleNamespace(username="b@x.ma"), "Sent", b"From: b@x.ma\r\n\r\nB", now, boom)
    (tmp_path / "envoyes_a_copier" / "1-1.eml").write_bytes(b"From: b@x.ma\r\n\r\nancien")  # fichier d'avant la V3.8
    assert len(sent_copy.pending("a@x.ma")) == 1                   # seulement les siennes
    assert len(sent_copy.pending("b@x.ma")) == 2                   # les siennes + l'ancien fichier dont il est l'expéditeur
    assert len(sent_copy.pending()) == 3


def test_settings_refuse_inbox_as_sent_folder():
    from app.web.api_common import FormLike
    from app.web.routes_settings import _read_mailbox_form
    _, errors = _read_mailbox_form(FormLike({"display_name": "O", "email": "o@x.ma", "smtp_host": "smtp.x.ma", "smtp_port": 465,
                                             "imap_host": "imap.x.ma", "imap_port": 993, "username": "o@x.ma", "sent_folder": "INBOX"}))
    assert "sent_folder" in errors


def test_multirisque_bureau_asks_building_value_not_surface(world):  # noqa: F811
    """Demande d'Omar (12/11) : valeur du contenu ET valeur du bâtiment, plus de superficie ;
    le modèle d'email C12 déjà installé est mis à jour s'il n'a pas été retouché."""
    from app import quotes, settings_store, starter_data
    from app.models import Sequence, Step
    mrb = quotes.branch_def("Multirisque bureau")
    keys = [f["key"] for f in mrb["fields"]]
    assert "valeur_batiment" in keys and "valeur_contenu" in keys and "superficie" not in keys
    fix = next(f for f in starter_data.load_sequences()["replace_texts"] if f["name"] == "C12 · Cotation Multirisque bureau")
    with get_session() as s:
        seq = s.scalars(select(Sequence).where(Sequence.name == fix["name"])).first()
        if seq is None:
            spec = next(x for x in starter_data.load_sequences()["sequences"] if x["name"] == fix["name"])
            seq = Sequence(name=fix["name"], category=spec["category"], branch="Multirisque bureau")
            s.add(seq)
            s.flush()
            s.add(Step(sequence_id=seq.id, position=1, delay_days=0, body_template=fix["old"]))
        else:
            s.scalars(select(Step).where(Step.sequence_id == seq.id, Step.position == 1)).one().body_template = fix["old"]
        settings_store.set_(s, "starter_sequences_version", 6)
        s.commit()
        starter_data.apply_sequences(s)
        s.commit()
        body = s.scalars(select(Step).where(Step.sequence_id == seq.id, Step.position == 1)).one().body_template
        assert "[Valeur du bâtiment]" in body and "Superficie" not in body

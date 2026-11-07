"""V2.8 : pièces jointes, types de séquence (prospection / gestion / souscription), service et
niveau des contacts d'assureurs, logos, agenda et centre de notifications."""
from datetime import date, timedelta
from email import message_from_bytes, policy

from sqlalchemy import select

from app import attachments_service, importer, settings_store
from app import campaigns_service as camp_svc
from app import companies_service as co
from app import sequences_service as ss
from app.db import get_session
from app.models import Campaign, Contact, Enrollment, Message, Reminder, Sequence, Step, StepVariant
from app.timeutil import to_local, utcnow
from tests.conftest import USER
from tests.test_m4_engine import START, _activate, _run, world  # noqa: F401

ORIGIN = {"Origin": "http://testserver"}
PDF = b"%PDF-1.4 plaquette ODDO"


def _upload(client, name="plaquette.pdf", data=PDF, ctype="application/pdf"):
    return client.post("/api/attachments", files={"file": (name, data, ctype)}, headers=ORIGIN)


def _parts(raw: bytes):
    msg = message_from_bytes(raw, policy=policy.default)
    return msg, [(p.get_filename(), p.get_content()) for p in msg.iter_attachments()]


# ------------------------------------------------------------------ pièces jointes

def test_upload_rules(client, db):
    r = _upload(client)
    assert r.status_code == 200 and r.json()["name"] == "plaquette.pdf" and r.json()["size"] == len(PDF)
    assert client.get(f"/api/attachments/{r.json()['id']}").content == PDF
    assert _upload(client, "virus.exe", b"MZ").status_code == 422
    assert _upload(client, "vide.pdf", b"").status_code == 422
    big = b"x" * (attachments_service.MAX_EMAIL_BYTES + 1)
    assert _upload(client, "gros.pdf", big).status_code == 422
    assert _upload(client, "../../etc/passwd.pdf").json()["name"] == "passwd.pdf"  # pas de chemin


def test_first_step_attachment_is_sent_by_engine(client, world):  # noqa: F811
    att = _upload(client).json()
    with get_session() as s:
        seq_id = s.get(Campaign, world["campaign_id"]).sequence_id
    full = client.get(f"/api/sequences/{seq_id}").json()
    steps = full["steps"]
    steps[0]["attachment_ids"] = [att["id"]]
    r = client.put(f"/api/sequences/{seq_id}", json={"name": full["name"], "steps": steps}, headers=ORIGIN)
    assert r.status_code == 200, r.text
    again = client.get(f"/api/sequences/{seq_id}").json()["steps"]
    assert [a["name"] for a in again[0]["attachments"]] == ["plaquette.pdf"] and again[1]["attachments"] == []

    assert _activate(world["campaign_id"]) == 3
    _run(until=START + timedelta(days=21))
    by_step = {}
    with get_session() as s:
        for m in s.scalars(select(Message).where(Message.direction == "out")):
            by_step.setdefault(m.step_position, []).append(m.attachments)
    assert by_step[1] == [["plaquette.pdf"]] * 3 and all(a is None for a in by_step[2])
    first = [m for m in world["smtp"].messages if _parts(m.data)[1]]
    assert len(first) == 3 and _parts(first[0].data)[1] == [("plaquette.pdf", PDF)]
    # la copie dans « Envoyés » contient aussi la pièce jointe
    assert any(b"plaquette.pdf" in raw for _, _, raw in world["imap"].folders["INBOX.Sent"].messages)


def test_too_heavy_step_is_refused(client, world):  # noqa: F811
    a = _upload(client, "a.pdf", b"a" * (6 * 1024 * 1024)).json()
    b = _upload(client, "b.pdf", b"b" * (6 * 1024 * 1024)).json()
    with get_session() as s:
        seq_id = s.get(Campaign, world["campaign_id"]).sequence_id
    full = client.get(f"/api/sequences/{seq_id}").json()
    full["steps"][0]["attachment_ids"] = [a["id"], b["id"]]
    assert client.put(f"/api/sequences/{seq_id}", json={"name": full["name"], "steps": full["steps"]},
                      headers=ORIGIN).status_code == 422


def test_manual_mail_with_attachment(client, world):  # noqa: F811
    att = _upload(client, "devis.pdf").json()
    r = client.post("/api/mailbox/send", json={"to": "contact0@societe0.ma", "subject": "Votre devis", "body": "Ci-joint.",
                                                "attachment_ids": [att["id"]]}, headers=ORIGIN)
    assert r.status_code == 200, r.text
    (sent,) = world["smtp"].messages
    msg, parts = _parts(sent.data)
    assert parts == [("devis.pdf", PDF)] and "List-Unsubscribe" not in msg
    with get_session() as s:
        m = s.scalars(select(Message).where(Message.subject == "Votre devis")).one()
        assert m.attachments == ["devis.pdf"]
    bad = client.post("/api/mailbox/send", json={"to": "x@y.ma", "subject": "s", "body": "b", "attachment_ids": [999]},
                      headers=ORIGIN)
    assert bad.status_code == 422


# ------------------------------------------------------------------ types de séquence

def _make_client_and_gestion(world):
    """Contact 0 devient client ; une séquence « gestion » et sa campagne."""
    with get_session() as s:
        c0 = s.scalars(select(Contact).where(Contact.email == "contact0@societe0.ma")).one()
        co.set_contact_kind(s, c0, "client")
        src = s.get(Campaign, world["campaign_id"])
        seq = s.get(Sequence, src.sequence_id)
        seq_g = Sequence(name="Renouvellement", category="gestion")
        s.add(seq_g)
        s.flush()
        for st in ss.steps_of(s, seq):
            s.add(Step(sequence_id=seq_g.id, position=st.position, delay_days=st.delay_days,
                       business_days=st.business_days, same_thread=st.same_thread, body_template=st.body_template))
        s.flush()
        for st, new in zip(ss.steps_of(s, seq), ss.steps_of(s, seq_g)):
            for v in ss.variants_of(s, st).values():
                s.add(StepVariant(step_id=new.id, label=v.label, subject_template=v.subject_template))
        camp = Campaign(name="Gestion", mailbox_id=src.mailbox_id, sequence_id=seq_g.id, filters={}, status="draft")
        s.add(camp)
        s.commit()
        return c0.id, seq_g.id, camp.id


def test_categories_api(client, world):  # noqa: F811
    r = client.post("/api/sequences", json={"name": "Suivi souscription", "category": "souscription"}, headers=ORIGIN)
    sid = r.json()["id"]
    lst = client.get("/api/sequences").json()
    assert {c["value"] for c in lst["categories"]} >= {"prospection", "gestion", "souscription"}
    assert next(i for i in lst["items"] if i["id"] == sid)["category"] == "souscription"
    assert client.post("/api/sequences", json={"name": "x", "category": "autre"}, headers=ORIGIN).status_code == 422
    dup = client.post(f"/api/sequences/{sid}/duplicate", headers=ORIGIN).json()["id"]
    assert client.get(f"/api/sequences/{dup}").json()["category"] == "souscription"
    # une séquence déjà utilisée par une campagne ne change pas de type
    with get_session() as s:
        used = s.get(Campaign, world["campaign_id"]).sequence_id
    full = client.get(f"/api/sequences/{used}").json()
    assert client.put(f"/api/sequences/{used}", json={"name": full["name"], "category": "gestion", "steps": full["steps"]},
                      headers=ORIGIN).status_code == 409


def test_prospection_never_targets_clients_but_gestion_does(client, world):  # noqa: F811
    c0, seq_g, camp_g = _make_client_and_gestion(world)
    with get_session() as s:
        prosp = camp_svc.candidates(s, s.get(Campaign, world["campaign_id"]))
        gest = camp_svc.candidates(s, s.get(Campaign, camp_g))
        ids_p = {x.contact.id for x in prosp if not x.excluded}
        ids_g = {x.contact.id for x in gest if not x.excluded}
    assert c0 not in ids_p and c0 in ids_g and len(ids_g) == 3
    cnt = client.get("/api/contacts/count?category=gestion").json()
    assert cnt["protected"] == 0
    assert client.get("/api/contacts/count").json()["protected"] >= 1


def test_gestion_email_has_no_stop_line_and_survives_kind_change(client, world):  # noqa: F811
    c0, seq_g, camp_g = _make_client_and_gestion(world)
    with get_session() as s:
        camp = s.get(Campaign, camp_g)
        camp.filters = {"kind": "client"}
        s.commit()
    assert _activate(camp_g) == 1
    _run(until=START + timedelta(days=1))
    raws = [m.data for m in world["smtp"].messages]
    assert raws, "au moins le premier email de gestion"
    msg = message_from_bytes(raws[0], policy=policy.default)
    assert "List-Unsubscribe" not in msg
    assert "STOP" not in msg.get_body(("plain",)).get_content()
    with get_session() as s:
        stopped = co.set_contact_kind(s, s.get(Contact, c0), "insurer")
        s.commit()
        enr = s.scalars(select(Enrollment).where(Enrollment.campaign_id == camp_g)).one()
    assert stopped == 0 and enr.status not in ("stopped",)


def test_preview_of_gestion_has_no_unsubscribe(world):  # noqa: F811
    _, seq_g, _ = _make_client_and_gestion(world)
    with get_session() as s:
        line = settings_store.get(s, "unsubscribe_line")
        assert ss.unsubscribe_for(s, s.get(Sequence, seq_g)) == ""
        assert ss.unsubscribe_for(s, s.scalars(select(Sequence).where(Sequence.category == "prospection")).first()) == line


# ------------------------------------------------------------------ service et niveau, logos

def test_department_and_seniority(client, db):
    r = client.post("/api/contacts", json={"email": "n@wafa.ma", "first_name": "Nadia", "company": "Wafa Assurance",
                                           "kind": "insurer", "department": "souscription", "seniority": "directeur"},
                    headers=ORIGIN)
    assert r.status_code == 200, r.text
    cid = r.json()["id"]
    d = client.get(f"/api/contacts/{cid}").json()
    assert d["department"] == "souscription" and d["seniority"] == "directeur"
    assert client.put(f"/api/contacts/{cid}", json={"department": "cuisine"}, headers=ORIGIN).status_code == 422
    comp = client.get(f"/api/contacts/{cid}").json()["company_ref"]["id"]
    people = client.get(f"/api/companies/{comp}").json()["people"]
    assert people[0]["department"] == "souscription" and people[0]["seniority"] == "directeur"
    voc = client.get("/api/vocab").json() if client.get("/api/vocab").status_code == 200 else None
    if voc:
        assert {d["value"] for d in voc["departments"]} == {"souscription", "gestion", "production", "maritime_transport", "autre"}


def test_import_maps_service_and_level():
    assert importer.AUTO_MAP["service"] == "department" and importer.AUTO_MAP["niveau"] == "seniority"
    assert importer.DEPARTMENT_WORDS[importer.norm("Maritime / transport")] == "maritime_transport"
    assert importer.SENIORITY_WORDS[importer.norm("Directeur de département")] == "directeur"


def test_logo(client, db):
    cid = client.post("/api/companies", json={"name": "AXA Assurance Maroc", "kind": "insurer"}, headers=ORIGIN).json()["id"]
    png = b"\x89PNG\r\n\x1a\n" + b"0" * 50
    r = client.post(f"/api/companies/{cid}/logo", files={"file": ("axa.png", png, "image/png")}, headers=ORIGIN)
    assert r.status_code == 200
    url = r.json()["logo"]
    assert client.get(f"/api/companies/{cid}").json()["logo"] == url
    g = client.get(url)
    assert g.content == png and g.headers["content-type"] == "image/png"
    assert client.post(f"/api/companies/{cid}/logo", files={"file": ("x.gif", png, "image/gif")},
                       headers=ORIGIN).status_code == 422
    assert client.delete(f"/api/companies/{cid}/logo", headers=ORIGIN).status_code == 200
    assert client.get(f"/api/companies/{cid}").json()["logo"] is None


# ------------------------------------------------------------------ agenda et notifications

def test_reminders_crud_and_notifications(client, world):  # noqa: F811
    today = to_local(utcnow()).date()
    with get_session() as s:
        c0 = s.scalars(select(Contact).where(Contact.email == "contact0@societe0.ma")).one().id
    r = client.post("/api/reminders", json={"kind": "call", "title": "Point sur le contrat flotte", "due_on": today.isoformat(),
                                             "due_time": "10:00", "contact_id": c0}, headers=ORIGIN)
    assert r.status_code == 200, r.text
    rid = r.json()["id"]
    assert r.json()["contact"]["company"] == "Société 0"
    later = client.post("/api/reminders", json={"kind": "renewal", "title": "Renouvellement RC",
                                                 "due_on": (today + timedelta(days=20)).isoformat()}, headers=ORIGIN).json()
    assert client.post("/api/reminders", json={"title": "", "due_on": "pas une date"}, headers=ORIGIN).status_code == 422
    items = client.get(f"/api/reminders?start={today.isoformat()}&end={(today + timedelta(days=30)).isoformat()}").json()["items"]
    assert [i["id"] for i in items] == [rid, later["id"]]
    assert [i["id"] for i in client.get(f"/api/reminders?contact_id={c0}").json()["items"]] == [rid]

    n = client.get("/api/notifications").json()
    mine = [i for i in n["items"] if i["type"] == "reminder"]
    assert len(mine) == 1 and mine[0]["title"] == "Point sur le contrat flotte" and mine[0]["detail"].startswith("Appeler") and "Prénom0" in mine[0]["detail"]
    assert n["unseen"] >= 1
    client.post("/api/notifications/seen", json={"keys": [mine[0]["key"]]}, headers=ORIGIN)
    n2 = client.get("/api/notifications").json()
    assert next(i for i in n2["items"] if i["key"] == mine[0]["key"])["seen"] is True
    assert n2["unseen"] == n["unseen"] - 1

    assert client.put(f"/api/reminders/{rid}", json={"done": True}, headers=ORIGIN).json()["done"] is True
    assert not [i for i in client.get("/api/notifications").json()["items"] if i["type"] == "reminder"]
    assert client.delete(f"/api/reminders/{later['id']}", headers=ORIGIN).status_code == 200
    with get_session() as s:
        assert s.scalar(select(Reminder.id).where(Reminder.id == later["id"])) is None


def test_followup_notification_links_to_the_person(client, world):  # noqa: F811
    with get_session() as s:
        c = s.scalars(select(Contact).where(Contact.email == "contact1@societe1.ma")).one()
        s.add(Message(contact_id=c.id, direction="out", message_id="<old@oddo.ma>", to_email=c.email, subject="Vos contrats",
                      body_text="Bonjour", sent_at=utcnow() - timedelta(days=12)))
        s.commit()
        cid = c.id
    items = client.get("/api/notifications").json()["items"]
    fu = [i for i in items if i["type"] == "followup"]
    assert len(fu) == 1 and fu[0]["href"] == f"/inbox/followups?contact={cid}"
    assert "Prénom1 Test" in fu[0]["title"]
    client.post("/api/notifications/seen", json={}, headers=ORIGIN)  # tout marquer comme vu
    assert client.get("/api/notifications").json()["unseen"] == 0


def test_callbacks_appear_in_agenda(client, world):  # noqa: F811
    today = to_local(utcnow()).date()
    with get_session() as s:
        c = s.scalars(select(Contact).where(Contact.email == "contact2@societe2.ma")).one()
        s.add(Message(contact_id=c.id, direction="in", message_id="<rep@x.ma>", subject="Re", body_text="Rappelez-moi",
                      received_at=utcnow(), kind="reply", classification="later", callback_on=today, note="après le 15"))
        s.commit()
    items = client.get("/api/reminders").json()["items"]
    cb = [i for i in items if i["source"] == "callback"]
    assert len(cb) == 1 and cb[0]["notes"] == "après le 15"
    assert any(i["type"] == "callback" for i in client.get("/api/notifications").json()["items"])
    assert isinstance(date.fromisoformat(cb[0]["due_on"]), date) and USER


# ================================================================== V2.9

def test_send_sequence_to_one_person_with_personalised_first_email(client, world):  # noqa: F811
    with get_session() as s:
        seq_id = s.get(Campaign, world["campaign_id"]).sequence_id
        c0 = s.scalars(select(Contact).where(Contact.email == "contact0@societe0.ma")).one().id
    d = client.get(f"/api/sequences/{seq_id}/draft?contact_id={c0}").json()
    assert d["steps"][0]["own_subject"] and "Société 0" in d["steps"][0]["body"]
    assert "Omar Douiri" not in d["steps"][0]["body"]  # sans signature : elle s'ajoute à l'envoi
    r = client.post(f"/api/sequences/{seq_id}/send", json={"contact_ids": [c0], "overrides": {
        "1": {"subject": "Pour {{ entreprise }}, en direct", "body": "Bonjour Prénom0,\n\nSuite à notre appel, voici ma proposition."}}},
        headers=ORIGIN).json()
    assert len(r["sent"]) == 1 and not r["refused"] and r["campaign"]["name"].startswith("À l'unité")
    again = client.post(f"/api/sequences/{seq_id}/send", json={"contact_ids": [c0]}, headers=ORIGIN).json()
    assert again["refused"][0]["reason"].startswith("Cette personne a déjà reçu")
    _run(until=START + timedelta(days=21))
    msgs = [message_from_bytes(m.data, policy=policy.default) for m in world["smtp"].messages]
    first = msgs[0]
    assert "Pour Société 0, en direct" in first["Subject"]
    body = first.get_body(("plain",)).get_content()
    assert "Suite à notre appel" in body and "Omar Douiri" in body and "STOP" in body  # signature + STOP (prospection)
    assert len(msgs) == 3 and "Re: Pour Société 0, en direct" in msgs[1]["Subject"]  # relances dans le même fil
    with get_session() as s:
        camp = s.scalars(select(Campaign).where(Campaign.direct.is_(True))).one()
        assert camp.status == "active" and camp.sequence_id == seq_id


def test_send_to_several_people_reports_refusals(client, world):  # noqa: F811
    c0, seq_g, _ = _make_client_and_gestion(world)  # c0 devient client
    with get_session() as s:
        seq_p = s.get(Campaign, world["campaign_id"]).sequence_id
        ids = list(s.scalars(select(Contact.id).order_by(Contact.id)))
    r = client.post(f"/api/sequences/{seq_p}/send", json={"contact_ids": ids}, headers=ORIGIN).json()
    assert len(r["sent"]) == 2 and len(r["refused"]) == 1 and "prospection" in r["refused"][0]["reason"]
    g = client.post(f"/api/sequences/{seq_g}/send", json={"contact_ids": [c0]}, headers=ORIGIN).json()
    assert len(g["sent"]) == 1  # gestion : un client peut la recevoir


def test_personalising_fixes_unfinished_texts(client, world):  # noqa: F811
    with get_session() as s:
        seq_id = s.get(Campaign, world["campaign_id"]).sequence_id
        st = ss.steps_of(s, s.get(Sequence, seq_id))[0]
        st.body_template = "Bonjour,\n\nÀ RÉDIGER plus tard."
        s.commit()
        c1 = s.scalars(select(Contact).where(Contact.email == "contact1@societe1.ma")).one().id
    refused = client.post(f"/api/sequences/{seq_id}/send", json={"contact_ids": [c1]}, headers=ORIGIN).json()
    assert refused["refused"] and refused["refused"][0]["problems"]
    ok = client.post(f"/api/sequences/{seq_id}/send", json={"contact_ids": [c1], "overrides": {"1": {"body": "Bonjour, texte écrit pour lui."}}},
                     headers=ORIGIN).json()
    assert len(ok["sent"]) == 1


def test_add_and_remove_function_and_sector(client, db):
    from app import vocab
    try:
        r = client.post("/api/blocks", json={"kind": "target", "label": "Achats"}, headers=ORIGIN)
        assert r.status_code == 200, r.text
        b = r.json()
        assert b["key"] == "ACH" and b["todo"] and b["custom"]
        sec = client.post("/api/blocks", json={"kind": "sector", "label": "Hôtellerie & tourisme"}, headers=ORIGIN).json()
        assert sec["key"] == "HOT"
        assert client.post("/api/blocks", json={"kind": "target", "label": "achats"}, headers=ORIGIN).status_code == 422
        assert client.post("/api/blocks", json={"kind": "sector", "label": "BTP & immobilier"}, headers=ORIGIN).status_code == 422
        voc = client.get("/api/contacts").json()["vocab"]
        assert {"value": "Achats", "label": "Achats", "code": "ACH"} in voc["targets"]
        assert vocab.sequence_code("Achats", "Hôtellerie & tourisme") == "ACH-HOT"
        cid = client.post("/api/contacts", json={"email": "a@hotel.ma", "first_name": "Aya", "target_segment": "Achats",
                                                 "sector_family": "Hôtellerie & tourisme"}, headers=ORIGIN).json()["id"]
        assert client.get(f"/api/contacts/{cid}").json()["sequence_code"] == "ACH-HOT"
        client.put(f"/api/blocks/{b['id']}", json={"body": "Pour les acheteurs de {{ entreprise }}."}, headers=ORIGIN)
        # le texte s'applique dans l'aperçu de ce contact
        seq_id = client.get("/api/sequences").json()["items"][0]["id"]
        prev = client.get(f"/api/sequences/{seq_id}/preview?contact_id={cid}").json()
        assert "Pour les acheteurs de" in prev["steps"][0]["body"]
        assert client.delete(f"/api/blocks/{b['id']}", headers=ORIGIN).status_code == 409  # utilisé par Aya
        fixed = [x for x in client.get("/api/blocks").json() if not x["custom"]][0]
        assert client.delete(f"/api/blocks/{fixed['id']}", headers=ORIGIN).status_code == 409
    finally:
        vocab.TARGETS.pop("ACH", None); vocab.SECTORS.pop("HOT", None)
        from app.seed import SECTOR_BLOCKS, TARGET_BLOCKS
        TARGET_BLOCKS.pop("ACH", None); SECTOR_BLOCKS.pop("HOT", None)


def test_migration_0008_columns(db):
    from sqlalchemy import inspect
    from app.db import get_engine
    insp = inspect(get_engine())
    assert "label" in {c["name"] for c in insp.get_columns("content_block")}
    assert "direct" in {c["name"] for c in insp.get_columns("campaign")}
    assert "overrides" in {c["name"] for c in insp.get_columns("enrollment")}


# ================================================================== V2.10

def test_campaign_with_hand_picked_people(client, world):  # noqa: F811
    with get_session() as s:
        seq_id = s.get(Campaign, world["campaign_id"]).sequence_id
        ids = list(s.scalars(select(Contact.id).order_by(Contact.id)))[:2]
    pick = ",".join(map(str, ids))
    cnt = client.get(f"/api/contacts/count?contact_ids={pick}").json()
    assert cnt["active"] == 2 and cnt["matching"] == 2
    r = client.post("/api/campaigns", json={"name": "Deux personnes", "sequence_id": seq_id, "filters": {"contact_ids": pick}},
                    headers=ORIGIN)
    assert r.status_code == 200, r.text
    cid = r.json()["id"]
    rep = client.get(f"/api/campaigns/{cid}/activation").json()
    assert rep["eligible"] == 2
    assert client.post(f"/api/campaigns/{cid}/activate", json={"overlap": False}, headers=ORIGIN).json()["enrolled"] == 2
    with get_session() as s:
        assert sorted(s.scalars(select(Enrollment.contact_id).where(Enrollment.campaign_id == cid))) == ids


def test_schedule_preview(client, world):  # noqa: F811
    seq_id = client.get("/api/sequences").json()["items"][0]["id"]
    sch = client.get(f"/api/sequences/{seq_id}/schedule").json()
    assert [x["position"] for x in sch] == [1, 2, 3] and all(x["planned_at"] for x in sch)
    assert sch[0]["planned_at"] < sch[1]["planned_at"] < sch[2]["planned_at"]

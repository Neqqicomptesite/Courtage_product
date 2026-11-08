"""Cotalis, phase 1 : dossiers de cotation (création, fiche de branche, consultation des
compagnies, relance dans l'agenda, réponse rattachée, étapes, cloisonnement par cabinet)."""
from email.message import EmailMessage
from email.utils import format_datetime

from sqlalchemy import select

from app import imap_sync, settings_store
from app.db import get_session
from app.models import Company, Contact, QuoteCase, Reminder
from app.scheduling import SendWindow
from app.timeutil import to_local, utcnow
from tests.conftest import USER
from tests.test_m4_engine import world  # noqa: F401

O = {"Origin": "http://testserver"}


def _setup():
    from app import starter_data
    with get_session() as s:
        starter_data.apply_sequences(s, force=True)  # modèles de cotation par branche (C1 à C10)
        s.commit()
        client_co = Company(name="Atlas Logistique", name_key="atlas logistique", kind="prospect")
        ins1 = Company(name="Assurance Alpha", name_key="assurance alpha", kind="insurer")
        ins2 = Company(name="Beta Assurances", name_key="beta assurances", kind="insurer")
        s.add_all([client_co, ins1, ins2])
        s.flush()
        s.add_all([
            Contact(email="dg@atlas-logistique.ma", first_name="Karim", last_name="Benali", company="Atlas Logistique",
                    company_id=client_co.id, kind="client"),
            Contact(email="gestion@alpha-assurance.ma", first_name="Sara", company_id=ins1.id, kind="insurer", department="gestion"),
            Contact(email="souscription@alpha-assurance.ma", first_name="Nadia", company_id=ins1.id, kind="insurer",
                    department="souscription"),
            Contact(email="cotations@beta-assurances.ma", first_name="Youssef", company_id=ins2.id, kind="insurer"),
        ])
        s.commit()
        return client_co.id, ins1.id, ins2.id


def _reply(to_msgid: str, sender: str, subject: str, with_pdf: bool = True) -> bytes:
    m = EmailMessage()
    m["From"], m["To"], m["Subject"] = sender, USER, subject
    m["Message-ID"] = "<offre-123@alpha-assurance.ma>"
    m["In-Reply-To"], m["References"] = to_msgid, to_msgid
    m["Date"] = format_datetime(utcnow())
    m.set_content("Bonjour,\nVeuillez trouver notre proposition ci-jointe.\nCordialement")
    if with_pdf:
        m.add_attachment(b"%PDF-1.4 offre", maintype="application", subtype="pdf", filename="Offre Alpha.pdf")
    return m.as_bytes()


def test_full_quote_flow(client, world):  # noqa: F811
    client_co, ins1, ins2 = _setup()
    r = client.post("/api/quotes", json={"branch": "Prévoyance", "company_id": client_co,
                                         "fields": {"activite": "Transport routier", "effectif": "42"}}, headers=O)
    assert r.status_code == 200, r.text
    case = r.json()
    assert case["ref"].startswith("COT-") and case["client_name"] == "Atlas Logistique"
    assert case["stage"] == "info" and "Masse salariale annuelle" in case["missing_labels"]

    # fiche complétée ; un champ hors branche est ignoré
    r = client.patch(f"/api/quotes/{case['id']}", json={"fields": {
        "formule": "DIM (dès le premier dirham)", "nb_conjoints": "30", "nb_enfants": "55",
        "masse_salariale": "6500000", "date_effet": "2027-01-01", "pirate": "x"}}, headers=O)
    case = r.json()
    assert case["missing_labels"] == [] and "pirate" not in case["fields"]

    # compagnies : l'interlocuteur « souscription » est choisi d'office
    case = client.post(f"/api/quotes/{case['id']}/insurers", json={"company_ids": [ins1, ins2, ins1]}, headers=O).json()
    assert [i["company"] for i in case["insurer_list"]] == ["Assurance Alpha", "Beta Assurances"]
    alpha = case["insurer_list"][0]
    assert alpha["contact"]["email"] == "souscription@alpha-assurance.ma"

    # brouillon rempli avec la fiche du dossier
    d = client.get(f"/api/quotes/{case['id']}/insurers/{alpha['id']}/draft").json()
    assert d["subject"] == "Demande de cotation Prévoyance (AMC / DIM) – Atlas Logistique"
    assert "Bonjour Nadia" in d["body"] and "Effectif : 42 salariés" in d["body"]
    assert "6 500 000 MAD" in d["body"] and "01/01/2027" in d["body"] and "DIM (dès le premier dirham)" in d["body"]
    assert d["missing"] == [] and not d["followup"]

    # un champ encore entre crochets bloque l'envoi
    bad = client.post(f"/api/quotes/{case['id']}/insurers/{alpha['id']}/send",
                      json={**d, "body": d["body"] + "\n[Pièce manquante]"}, headers=O)
    assert bad.status_code == 422 and "Pièce manquante" in bad.text

    r = client.post(f"/api/quotes/{case['id']}/insurers/{alpha['id']}/send", json=d, headers=O)
    assert r.status_code == 200, r.text
    case = r.json()
    alpha = case["insurer_list"][0]
    assert alpha["status"] == "sent" and case["stage"] == "consulting"
    assert len(world["smtp"].messages) == 1  # mode test : part vers la boîte de l'employé
    with get_session() as s:
        rem = s.scalars(select(Reminder).where(Reminder.quote_case_id == case["id"])).one()
        expected = SendWindow.from_settings(s).add_days(to_local(utcnow()).date(), 4, True)
        assert rem.due_on == expected and rem.kind == "quote" and rem.done_at is None
        assert settings_store.get(s, "quote_followup_days") == 4
        from app.models import QuoteEvent
        out_id = s.scalars(select(QuoteEvent.message_id).where(QuoteEvent.kind == "email_out")).one()

    # la compagnie répond dans le fil : rattachée au dossier, rappel clos
    world["imap"].deliver("INBOX", _reply(out_id, "souscription@alpha-assurance.ma", "Re: " + d["subject"]))
    rep = imap_sync.sync()
    assert rep.counts.get("quote_reply") == 1, rep.counts
    case = client.get(f"/api/quotes/{case['id']}").json()
    alpha = case["insurer_list"][0]
    assert alpha["status"] == "replied"
    ev = next(e for e in case["events"] if e["kind"] == "email_in")
    assert ev["data"]["attachments"][0]["name"] == "Offre Alpha.pdf" and ev["mine"]
    assert "proposition ci-jointe" in ev["data"]["body"]
    with get_session() as s:
        assert s.scalars(select(Reminder).where(Reminder.quote_case_id == case["id"])).one().done_at is not None
    assert imap_sync.sync().counts.get("quote_reply") is None   # pas deux fois

    # la pièce jointe reçue est rangée comme offre : statut « Offre reçue », dossier en « Offres reçues »
    r = client.post(f"/api/quotes/{case['id']}/files/from-mail", headers=O, json={
        "folder": ev["data"]["folder"], "uid": ev["data"]["uid"], "index": ev["data"]["attachments"][0]["index"],
        "kind": "offer", "insurer_id": alpha["id"]})
    assert r.status_code == 200, r.text
    case = r.json()
    assert case["files"][0]["name"] == "Offre Alpha.pdf" and case["files"][0]["kind"] == "offer"
    assert case["insurer_list"][0]["status"] == "offer" and case["stage"] == "offers"
    case = client.patch(f"/api/quotes/{case['id']}/insurers/{alpha['id']}", json={"offer_premium": "182 500"}, headers=O).json()
    assert case["best_offer"] == 182500

    # relance de Beta : d'abord la demande, puis une relance dans le même fil
    beta = case["insurer_list"][1]
    d2 = client.get(f"/api/quotes/{case['id']}/insurers/{beta['id']}/draft").json()
    client.post(f"/api/quotes/{case['id']}/insurers/{beta['id']}/send", json=d2, headers=O)
    f = client.get(f"/api/quotes/{case['id']}/insurers/{beta['id']}/draft").json()
    assert f["followup"] and f["subject"].startswith("Re: Demande de cotation") and f["in_reply_to"]
    assert "revenir vers vous" in f["body"]
    case = client.post(f"/api/quotes/{case['id']}/insurers/{beta['id']}/send", json=f, headers=O).json()
    assert case["insurer_list"][1]["status"] == "reminded" and case["insurer_list"][1]["reminders_sent"] == 1
    raw = world["smtp"].messages[-1].data.decode()
    assert "In-Reply-To:" in raw

    # une compagnie déjà consultée ne se retire pas
    assert client.delete(f"/api/quotes/{case['id']}/insurers/{beta['id']}", headers=O).status_code == 422

    # perdu : motif obligatoire ; puis tous les rappels du dossier sont clos
    assert client.patch(f"/api/quotes/{case['id']}", json={"stage": "lost"}, headers=O).status_code == 422
    case = client.patch(f"/api/quotes/{case['id']}", json={"stage": "lost", "lost_reason": "Prix"}, headers=O).json()
    assert case["stage"] == "lost" and case["closed_at"]
    with get_session() as s:
        assert all(r.done_at for r in s.scalars(select(Reminder).where(Reminder.quote_case_id == case["id"])))
    kinds = [e["kind"] for e in case["events"]]
    assert {"created", "fields", "insurer", "email_out", "email_in", "file", "stage"} <= set(kinds)

    # l'agenda connaît le dossier lié
    items = client.get("/api/reminders").json()
    if isinstance(items, dict):
        items = items.get("items", [])
    assert any(i.get("quote_case_id") == case["id"] for i in items)


def test_note_numbering_and_other_cabinet_hidden(client, world):  # noqa: F811
    client_co, *_ = _setup()
    a = client.post("/api/quotes", json={"branch": "Flotte", "client_name": "M. Test"}, headers=O).json()
    b = client.post("/api/quotes", json={"branch": "Transport", "company_id": client_co}, headers=O).json()
    assert int(b["ref"][-4:]) == int(a["ref"][-4:]) + 1
    assert client.post(f"/api/quotes/{a['id']}/notes", json={"text": "Client pressé"}, headers=O).json()["events"][0]["text"] == "Client pressé"
    assert client.post("/api/quotes", json={"client_name": "X"}, headers=O).status_code == 422
    # un dossier d'un autre cabinet (org_id 2) n'apparaît nulle part
    with get_session() as s:
        other = QuoteCase(org_id=2, ref="COT-2026-9999", branch="Flotte", client_name="Autre cabinet", title="x", fields={})
        s.add(other)
        s.commit()
        oid = other.id
    assert all(i["id"] != oid for i in client.get("/api/quotes").json()["items"])
    assert client.get(f"/api/quotes/{oid}").status_code == 404
    assert client.patch(f"/api/quotes/{oid}", json={"notes": "x"}, headers=O).status_code == 404
    assert client.get("/api/quotes?company_id=%d" % client_co).json()["items"][0]["id"] == b["id"]


def test_unknown_branch_has_generic_template(client, world):  # noqa: F811
    _, ins1, _ = _setup()
    c = client.post("/api/quotes", json={"branch": "Cyber-risques", "client_name": "Société Z", "insurer_ids": [ins1]}, headers=O).json()
    assert c["branch_def"]["fields"] == [] and c["stage"] == "new"
    d = client.get(f"/api/quotes/{c['id']}/insurers/{c['insurer_list'][0]['id']}/draft").json()
    assert d["subject"] == "Demande de cotation Cyber-risques – Société Z" and d["missing"] == []

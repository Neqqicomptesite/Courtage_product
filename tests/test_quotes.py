"""Dossiers de cotation : création (une ou plusieurs branches), fiche, consultation des
compagnies (email commun ou par branche, plusieurs destinataires, envoi à toutes), relances,
réponse rattachée, étapes (offres partielles / toutes reçues), renégociation, rappels,
documents, cloisonnement par cabinet."""
from email.message import EmailMessage
from email.utils import format_datetime

from sqlalchemy import select

from app import imap_sync, settings_store
from app.db import get_session
from app.models import Company, Contact, QuoteCase, QuoteEvent, Reminder
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
            Contact(email="sante@alpha-assurance.ma", first_name="Rachid", company_id=ins1.id, kind="insurer",
                    department="souscription"),
            Contact(email="cotations@beta-assurances.ma", first_name="Youssef", company_id=ins2.id, kind="insurer"),
        ])
        s.commit()
        return client_co.id, ins1.id, ins2.id


def _reply(to_msgid: str, sender: str, subject: str, with_pdf: bool = True, mid: str = "<offre-123@alpha-assurance.ma>") -> bytes:
    m = EmailMessage()
    m["From"], m["To"], m["Subject"] = sender, USER, subject
    m["Message-ID"] = mid
    m["In-Reply-To"], m["References"] = to_msgid, to_msgid
    m["Date"] = format_datetime(utcnow())
    m.set_content("Bonjour,\nVeuillez trouver notre proposition ci-jointe.\nCordialement")
    if with_pdf:
        m.add_attachment(b"%PDF-1.4 offre", maintype="application", subtype="pdf", filename="Offre Alpha.pdf")
    return m.as_bytes()


def _rows(case, company):
    return next(c for c in case["companies"] if c["company"] == company)["rows"]


def test_single_branch_flow(client, world):  # noqa: F811
    client_co, ins1, ins2 = _setup()
    r = client.post("/api/quotes", json={"branch": "Prévoyance", "company_id": client_co,
                                         "fields": {"activite": "Transport routier", "effectif": "42"}}, headers=O)
    assert r.status_code == 200, r.text
    case = r.json()
    assert case["ref"].startswith("COT-") and case["client_name"] == "Atlas Logistique" and case["branches"] == ["Prévoyance"]
    assert case["stage"] == "info" and "Masse salariale annuelle" in case["missing_labels"]
    assert "Date d'effet souhaitée" not in case["missing_labels"]   # facultative

    case = client.patch(f"/api/quotes/{case['id']}", json={"current_rate": "2,4 %", "fields": {
        "formule": "DIM (dès le premier dirham)", "nb_conjoints": "30", "nb_enfants": "55",
        "masse_salariale": "6500000", "pirate": "x"}}, headers=O).json()
    assert case["missing_labels"] == [] and "pirate" not in case["fields"] and case["current_rate"] == "2,4 %"

    case = client.post(f"/api/quotes/{case['id']}/insurers", json={"company_ids": [ins1, ins2, ins1]}, headers=O).json()
    assert [c["company"] for c in case["companies"]] == ["Assurance Alpha", "Beta Assurances"]
    alpha = _rows(case, "Assurance Alpha")[0]
    assert alpha["recipients"] == ["souscription@alpha-assurance.ma"]

    # brouillon : liste des interlocuteurs (souscription d'abord), date d'effet vide → ligne retirée
    d = client.post(f"/api/quotes/{case['id']}/draft", json={"insurer_ids": [alpha["id"]]}, headers=O).json()
    assert [o["department"] for o in d["options"]][:2] == ["souscription", "souscription"]
    assert d["subject"] == "Demande de cotation Prévoyance (AMC / DIM) – Atlas Logistique"
    assert "Bonjour Nadia" in d["body"] and "Effectif : 42 salariés" in d["body"] and "6 500 000 MAD" in d["body"]
    assert "Date d'effet" not in d["body"] and d["missing"] == [] and d["kind"] == "request"

    # deux souscripteurs dans le même email : « Bonjour Nadia et Rachid »
    d2 = client.post(f"/api/quotes/{case['id']}/draft", headers=O,
                     json={"insurer_ids": [alpha["id"]], "to": ["souscription@alpha-assurance.ma", "sante@alpha-assurance.ma"]}).json()
    assert "Bonjour Nadia et Rachid" in d2["body"]

    bad = client.post(f"/api/quotes/{case['id']}/send", headers=O,
                      json={**d2, "insurer_ids": [alpha["id"]], "body": d2["body"] + "\n[Pièce manquante]"})
    assert bad.status_code == 422 and "Pièce manquante" in bad.text

    r = client.post(f"/api/quotes/{case['id']}/send", json={**d2, "insurer_ids": [alpha["id"]]}, headers=O)
    assert r.status_code == 200, r.text
    case = r.json()
    alpha = _rows(case, "Assurance Alpha")[0]
    assert alpha["status"] == "sent" and case["stage"] == "consulting"
    assert alpha["recipients"] == ["souscription@alpha-assurance.ma", "sante@alpha-assurance.ma"]
    assert len(world["smtp"].messages) == 1
    with get_session() as s:
        rem = s.scalars(select(Reminder).where(Reminder.quote_case_id == case["id"])).one()
        assert rem.due_on == SendWindow.from_settings(s).add_days(to_local(utcnow()).date(), 4, True)
        assert rem.kind == "quote" and rem.done_at is None and settings_store.get(s, "quote_followup_days") == 4
        out_id = s.scalars(select(QuoteEvent.message_id).where(QuoteEvent.kind == "email_out")).one()

    # réponse dans le fil : rattachée, rappel clos, pas deux fois
    world["imap"].deliver("INBOX", _reply(out_id, "souscription@alpha-assurance.ma", "Re: " + d["subject"]))
    assert imap_sync.sync().counts.get("quote_reply") == 1
    case = client.get(f"/api/quotes/{case['id']}").json()
    assert _rows(case, "Assurance Alpha")[0]["status"] == "replied"
    ev = next(e for e in case["events"] if e["kind"] == "email_in")
    assert ev["data"]["attachments"][0]["name"] == "Offre Alpha.pdf" and ev["mine"]
    with get_session() as s:
        assert s.scalars(select(Reminder).where(Reminder.quote_case_id == case["id"])).one().done_at is not None
    assert imap_sync.sync().counts.get("quote_reply") is None

    # la pièce jointe rangée comme offre → « Offres partielles » (Beta n'a pas encore répondu)
    case = client.post(f"/api/quotes/{case['id']}/files/from-mail", headers=O, json={
        "folder": ev["data"]["folder"], "uid": ev["data"]["uid"], "index": ev["data"]["attachments"][0]["index"],
        "kind": "offer", "insurer_id": alpha["id"]}).json()
    assert case["files"][0]["kind"] == "offer" and _rows(case, "Assurance Alpha")[0]["status"] == "offer"
    assert case["stage"] == "partial"
    case = client.patch(f"/api/quotes/{case['id']}/insurers/{alpha['id']}", json={"offer_premium": "182 500", "offer_rate": "2,1 %"}, headers=O).json()
    assert case["best_offer"] == 182500 and _rows(case, "Assurance Alpha")[0]["offer_rate"] == "2,1 %"

    # Beta : envoi groupé (« envoyer à toutes »), puis relance dans le même fil
    res = client.post(f"/api/quotes/{case['id']}/send-all", json={}, headers=O).json()
    assert res["report"] == [{"company": "Beta Assurances", "ok": True, "to": ["cotations@beta-assurances.ma"]}]
    case = res["quote"]
    beta = _rows(case, "Beta Assurances")[0]
    f = client.post(f"/api/quotes/{case['id']}/draft", json={"insurer_ids": [beta["id"]]}, headers=O).json()
    assert f["followup"] and f["kind"] == "followup" and f["subject"].startswith("Re: Demande de cotation") and "revenir vers vous" in f["body"]
    case = client.post(f"/api/quotes/{case['id']}/send", json={**f, "insurer_ids": [beta["id"]]}, headers=O).json()
    assert _rows(case, "Beta Assurances")[0]["status"] == "reminded"
    assert "In-Reply-To:" in world["smtp"].messages[-1].data.decode()

    # Beta répond par un refus → toutes les compagnies ont répondu : « Toutes les offres reçues »
    case = client.patch(f"/api/quotes/{case['id']}/insurers/{beta['id']}", json={"status": "declined"}, headers=O).json()
    assert case["stage"] == "offers"

    # offre à renégocier : email de renégociation dans le fil, avec un point à préciser
    case = client.patch(f"/api/quotes/{case['id']}/insurers/{alpha['id']}", json={"status": "renegotiate"}, headers=O).json()
    rn = client.post(f"/api/quotes/{case['id']}/draft", json={"insurer_ids": [alpha["id"]]}, headers=O).json()
    assert rn["kind"] == "renegotiate" and "révision de vos conditions" in rn["body"] and rn["missing"]

    assert client.delete(f"/api/quotes/{case['id']}/insurers/{beta['id']}", headers=O).status_code == 422
    assert client.patch(f"/api/quotes/{case['id']}", json={"stage": "lost"}, headers=O).status_code == 422
    case = client.patch(f"/api/quotes/{case['id']}", json={"stage": "lost", "lost_reason": "Prix"}, headers=O).json()
    assert case["stage"] == "lost" and case["closed_at"]
    items = client.get("/api/reminders").json()
    items = items.get("items", items) if isinstance(items, dict) else items
    assert any(i.get("quote_case_id") == case["id"] for i in items)


def test_multi_branch_common_or_separate_emails(client, world):  # noqa: F811
    client_co, ins1, ins2 = _setup()
    case = client.post("/api/quotes", headers=O, json={
        "branches": ["Accidents du travail", "Prévoyance"], "company_id": client_co, "insurer_ids": [ins1, ins2],
        "fields": {"activite": "Logistique", "effectif": "42", "masse_salariale": "6500000", "formule": "AMC (complémentaire à l'AMO)",
                   "nb_conjoints": "10", "nb_enfants": "20"}}).json()
    assert case["branch_label"] == "Accidents du travail + Prévoyance" and case["missing_labels"] == []
    keys = [f["key"] for f in case["field_defs"]]
    assert keys.count("effectif") == 1   # champ commun saisi une seule fois
    eff = next(f for f in case["field_defs"] if f["key"] == "effectif")
    assert eff["branches"] == ["Accidents du travail", "Prévoyance"]
    alpha = _rows(case, "Assurance Alpha")
    assert [r["branch"] for r in alpha] == ["Accidents du travail", "Prévoyance"]

    # email commun aux deux branches
    d = client.post(f"/api/quotes/{case['id']}/draft", json={"insurer_ids": [r["id"] for r in alpha]}, headers=O).json()
    assert d["subject"] == "Demande de cotation Accidents du travail / Prévoyance – Atlas Logistique"
    assert "— Accidents du travail —" in d["body"] and "— Prévoyance —" in d["body"]
    assert d["body"].count("Bonjour") == 1 and "Formule : AMC" in d["body"] and d["missing"] == []
    case = client.post(f"/api/quotes/{case['id']}/send", json={**d, "insurer_ids": [r["id"] for r in alpha]}, headers=O).json()
    assert {r["status"] for r in _rows(case, "Assurance Alpha")} == {"sent"}

    # la réponse dans ce fil vaut pour les deux branches
    with get_session() as s:
        out_id = s.scalars(select(QuoteEvent.message_id).where(QuoteEvent.kind == "email_out")).one()
    world["imap"].deliver("INBOX", _reply(out_id, "souscription@alpha-assurance.ma", "Re: cotation", with_pdf=False))
    imap_sync.sync()
    case = client.get(f"/api/quotes/{case['id']}").json()
    assert {r["status"] for r in _rows(case, "Assurance Alpha")} == {"replied"}

    # Beta : un email par branche, à des personnes différentes
    beta = _rows(case, "Beta Assurances")
    at = client.post(f"/api/quotes/{case['id']}/draft", json={"insurer_ids": [beta[0]["id"]]}, headers=O).json()
    assert at["subject"].startswith("Demande de cotation Accidents du travail –") and "— " not in at["body"]
    case = client.post(f"/api/quotes/{case['id']}/send", headers=O, json={**at, "to": ["at@beta.test"], "insurer_ids": [beta[0]["id"]]}).json()
    rows = _rows(case, "Beta Assurances")
    assert rows[0]["status"] == "sent" and rows[0]["recipients"] == ["at@beta.test"] and rows[1]["status"] == "to_send"

    # un email ne mélange pas deux compagnies
    assert client.post(f"/api/quotes/{case['id']}/draft", json={"insurer_ids": [alpha[0]["id"], beta[1]["id"]]}, headers=O).status_code == 422

    # retirer une branche déjà envoyée : refusé ; ajouter une branche : lignes « À envoyer » créées
    assert client.patch(f"/api/quotes/{case['id']}", json={"branches": ["Prévoyance"]}, headers=O).status_code == 422
    case = client.patch(f"/api/quotes/{case['id']}", json={"branches": ["Accidents du travail", "Prévoyance", "Flotte"]}, headers=O).json()
    assert [r["branch"] for r in _rows(case, "Assurance Alpha")][-1] == "Flotte"
    assert "Nombre de véhicules" in case["missing_labels"]


def test_reminders_files_numbering_and_other_cabinet(client, world):  # noqa: F811
    client_co, *_ = _setup()
    a = client.post("/api/quotes", json={"branch": "Flotte", "client_name": "M. Test"}, headers=O).json()
    b = client.post("/api/quotes", json={"branch": "Transport", "company_id": client_co}, headers=O).json()
    assert int(b["ref"][-4:]) == int(a["ref"][-4:]) + 1
    assert client.post(f"/api/quotes/{a['id']}/notes", json={"text": "Client pressé"}, headers=O).json()["events"][0]["text"] == "Client pressé"
    assert client.post("/api/quotes", json={"client_name": "X"}, headers=O).status_code == 422

    # rappel lié au dossier : dans l'agenda et dans la cloche (lien vers le dossier)
    assert client.post(f"/api/quotes/{a['id']}/reminders", json={"title": "Réunir les infos"}, headers=O).status_code == 422
    today = to_local(utcnow()).date().isoformat()
    a = client.post(f"/api/quotes/{a['id']}/reminders", json={"title": "Réunir les infos client", "due_on": today, "due_time": "10:00"}, headers=O).json()
    assert a["reminders"][0]["title"] == "Réunir les infos client" and not a["reminders"][0]["done"]
    notes = client.get("/api/notifications").json()["items"]
    assert any(n["href"] == f"/quotes/{a['id']}" for n in notes)

    # documents : conditions actuelles (ancienne police…)
    att = client.post("/api/attachments", files={"file": ("police-2025.pdf", b"%PDF-1.4 x", "application/pdf")}, headers=O).json()
    a = client.post(f"/api/quotes/{a['id']}/files", json={"attachment_id": att["id"], "kind": "current", "label": "Police actuelle"}, headers=O).json()
    assert a["files"][0]["kind"] == "current"

    with get_session() as s:
        other = QuoteCase(org_id=2, ref="COT-2026-9999", branch="Flotte", branches=["Flotte"], client_name="Autre cabinet", title="x", fields={})
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
    assert c["field_defs"] == [] and c["stage"] == "new"
    d = client.post(f"/api/quotes/{c['id']}/draft", json={"insurer_ids": [_rows(c, "Assurance Alpha")[0]["id"]]}, headers=O).json()
    assert d["subject"] == "Demande de cotation Cyber-risques – Société Z" and d["missing"] == []

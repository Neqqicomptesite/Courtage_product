"""V2.1 : API complète utilisée par l'interface React (contacts, import, séquences, campagnes,
réponses, journal, réglages, graphique). Les règles métier sont déjà testées par les tests V1 :
ici on vérifie surtout le branchement et la forme des réponses."""
import io
from datetime import date

import openpyxl
from sqlalchemy import select

from app.db import get_session
from app.models import Campaign, Contact, Sequence, Step
from tests.conftest import PASSWORD, USER
from tests.test_m6_dashboard import dataset  # noqa: F401

ORIGIN = {"Origin": "http://testserver"}


def _xlsx(rows) -> bytes:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["Prénom", "Nom", "Email", "Entreprise", "Code séquence (cible × secteur)", "Accroche suggérée"])
    for r in rows:
        ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# ------------------------------------------------------------------ contacts

def test_contacts_list_filters_detail_and_actions(client, dataset):  # noqa: F811
    d = client.get("/api/contacts").json()
    assert d["total"] == 6 and len(d["items"]) == 6
    assert {"value": "active", "label": "Actif"} in d["options"]["status"]
    assert len(client.get("/api/contacts?sequence_code=FIN-IND").json()["items"]) == 2
    assert client.get("/api/contacts/count?sequence_code=RH-BTP").json() == {"matching": 2, "active": 2, "protected": 0}
    cid = dataset["contact_ids"][5]
    detail = client.get(f"/api/contacts/{cid}").json()
    assert detail["status_label"] == "Actif" and detail["enrollments"][0]["active"] is True
    assert any("Contact créé" in t["title"] for t in detail["timeline"])
    assert client.put(f"/api/contacts/{cid}/notes", json={"notes": "Rappeler"}, headers=ORIGIN).json()["ok"]
    assert client.post(f"/api/contacts/{cid}/do-not-contact", headers=ORIGIN).status_code == 200
    assert client.get(f"/api/contacts/{cid}").json()["status"] == "do_not_contact"
    assert client.post(f"/api/contacts/{cid}/reactivate", headers=ORIGIN).status_code == 200
    assert client.post(f"/api/contacts/{cid}/erase", json={"confirm": "non"}, headers=ORIGIN).status_code == 400
    assert client.post(f"/api/contacts/{cid}/erase", json={"confirm": "EFFACER"}, headers=ORIGIN).json()["ok"]
    assert client.get(f"/api/contacts/{cid}").status_code == 404


def test_import_wizard(client, db):
    data = _xlsx([["Salma", "B", "salma@client.ma", "Client", "FIN-IND", "Revue"],
                  ["Sans", "Email", "—", "X", "FIN-IND", ""]])
    up = client.post("/api/import", files={"file": ("leads.xlsx", data)}, headers=ORIGIN).json()
    assert up["rows"] == 2 and up["filename"] == "leads.xlsx"
    mapping = [c["mapping"] for c in up["columns"]]
    assert mapping[2] == "field:email" and mapping[5] == "custom:accroche_suggeree"
    prev = client.post(f"/api/import/{up['token']}/preview", json={"sheet": up["sheet"], "mapping": mapping},
                       headers=ORIGIN).json()
    assert prev["new"] == 1 and prev["ignored"][0]["reason"] == "Pas d'email"
    done = client.post(f"/api/import/{up['token']}/commit", json={"sheet": up["sheet"], "mapping": mapping},
                       headers=ORIGIN).json()
    assert {k: done[k] for k in ("new", "update", "ignore")} == {"new": 1, "update": 0, "ignore": 1}
    # V3.6 : les contacts du fichier forment une liste, proposée pour une campagne
    assert done["list"]["count"] == 1 and done["list"]["prospects"] == 1 and done["list"]["name"].startswith("Import leads.xlsx · ")
    bad = client.post("/api/import", files={"file": ("x.pdf", b"%PDF")}, headers=ORIGIN)
    assert bad.status_code == 400


def test_exclusions(client, dataset):  # noqa: F811
    r = client.post("/api/exclusions", json={"entry": "Entreprise0.ma"}, headers=ORIGIN).json()
    assert r["entry"] == "@entreprise0.ma" and r["affected"] == 1  # c0 passe en « Ne plus contacter »
    items = client.get("/api/exclusions").json()
    assert items[0]["kind"] == "domain" and items[0]["removable"]
    assert client.delete(f"/api/exclusions/{items[0]['id']}", headers=ORIGIN).json()["ok"]
    assert client.post("/api/exclusions", json={"entry": "pas un domaine"}, headers=ORIGIN).status_code == 400


# ----------------------------------------------------------------- séquences

def test_sequence_editor_roundtrip(client, dataset):  # noqa: F811
    lst = client.get("/api/sequences").json()
    sid = lst["items"][0]["id"]
    seq = client.get(f"/api/sequences/{sid}").json()
    assert [s["position"] for s in seq["steps"]] == [1, 2, 3] and "prenom" in seq["variables"]
    steps = seq["steps"]
    steps[0].update(subject_a="Objet {{ entreprise }}", subject_b="", body="Bonjour {{ prenom }}")
    steps[1].update(delay_days=5, business_days=False)
    saved = client.put(f"/api/sequences/{sid}", json={"name": "Renommée", "steps": steps}, headers=ORIGIN).json()
    assert saved["name"] == "Renommée" and saved["steps"][1]["delay_days"] == 5
    assert saved["steps"][0]["subject_b"] == ""
    prev = client.get(f"/api/sequences/{sid}/preview?contact_id={dataset['contact_ids'][0]}").json()
    assert prev["steps"][0]["subject"] == "Objet Entreprise 0" and prev["steps"][0]["body"].startswith("Bonjour Prénom0")
    assert prev["steps"][1]["subject"] == "Re: Objet Entreprise 0"
    # La séquence est utilisée par une campagne : supprimer une étape est refusé.
    assert client.delete(f"/api/sequences/{sid}/steps/{steps[1]['id']}", headers=ORIGIN).status_code == 400
    dup = client.post(f"/api/sequences/{sid}/duplicate", headers=ORIGIN).json()["id"]
    d = client.get(f"/api/sequences/{dup}").json()
    assert d["name"] == "Renommée (copie)" and len(d["steps"]) == 3 and d["campaigns"] == 0
    added = client.post(f"/api/sequences/{dup}/steps", headers=ORIGIN).json()
    assert len(added["steps"]) == 4
    removed = client.delete(f"/api/sequences/{dup}/steps/{added['steps'][1]['id']}", headers=ORIGIN).json()
    assert [s["position"] for s in removed["steps"]] == [1, 2, 3]
    assert client.delete(f"/api/sequences/{dup}", headers=ORIGIN).json()["ok"]


def test_blocks(client, db):
    from app.seed import run_seed
    with get_session() as s:
        run_seed(s)
        s.commit()
    blocks = client.get("/api/blocks").json()
    assert [b["key"] for b in blocks][:3] == ["FIN", "RH", "DIR"] and all(b["todo"] for b in blocks)
    r = client.put(f"/api/blocks/{blocks[0]['id']}", json={"body": "Trame finance."}, headers=ORIGIN).json()
    assert r["todo"] is False


def test_preview_send_goes_to_omar_only(client, dataset):  # noqa: F811
    with get_session() as s:
        for st in s.scalars(select(Step)):
            st.body_template = st.body_template.replace("À RÉDIGER", "Texte")
        s.commit()
    sid = client.get("/api/sequences").json()["items"][0]["id"]
    r = client.post(f"/api/sequences/{sid}/preview/send", json={"contact_id": dataset["contact_ids"][0]},
                    headers=ORIGIN).json()
    assert r == {"sent": 3, "to": USER}
    assert all(m.rcpt_tos == [USER] for m in dataset["smtp"].messages)


# ----------------------------------------------------------------- campagnes

def test_campaign_wizard_flow(client, dataset):  # noqa: F811
    with get_session() as s:
        for st in s.scalars(select(Step)):
            st.body_template = st.body_template.replace("À RÉDIGER", "Texte")
        from app.models import ContentBlock
        for b in s.scalars(select(ContentBlock)):
            b.body = "Bloc rédigé."
        s.add(Contact(email="nouveau@lead.ma", first_name="Nouveau", company="Lead", sequence_code="FIN-IND"))
        s.commit()
        seq_id = s.scalars(select(Sequence.id)).first()
    cid = client.post("/api/campaigns", json={"name": "Vague 2", "sequence_id": seq_id,
                                              "filters": {"sequence_code": "FIN-IND", "bidon": "x"}},
                      headers=ORIGIN).json()["id"]
    detail = client.get(f"/api/campaigns/{cid}").json()
    assert detail["status"] == "draft" and detail["filters"] == {"sequence_code": "FIN-IND"}
    free = {c["email"] for c in detail["candidates"] if not c["excluded"] and not c["other_campaigns"]}
    # c0 et c1 ont fini leur séquence dans « Vague 1 » (statut « a répondu », plus en cours) : éligibles.
    assert free == {"nouveau@lead.ma", "c0@entreprise0.ma", "c1@entreprise1.ma"}
    # V3.5 : c0 et c1 ont reçu « Vague 1 » il y a moins de 90 jours sans répondre : mis de côté…
    rep = client.get(f"/api/campaigns/{cid}/activation").json()
    assert rep["eligible"] == 1 and {c["email"] for c in rep["recent"]} == {"c0@entreprise0.ma", "c1@entreprise1.ma"}
    # … sauf si on choisit de les inclure quand même
    rep = client.get(f"/api/campaigns/{cid}/activation?recent=true").json()
    assert rep["eligible"] == 3 and not rep["blocked"] and rep["test_mode"] is True
    assert client.post(f"/api/campaigns/{cid}/activate", json={"recent": True}, headers=ORIGIN).json() == {"enrolled": 3}
    assert client.post(f"/api/campaigns/{cid}/pause", headers=ORIGIN).json()["ok"]
    assert client.post(f"/api/campaigns/{cid}/pause", headers=ORIGIN).status_code == 400
    assert client.post(f"/api/campaigns/{cid}/resume", headers=ORIGIN).json()["ok"]
    lst = client.get("/api/campaigns").json()
    assert {c["name"] for c in lst} == {"Vague 1", "Vague 2"}
    eid = client.get(f"/api/campaigns/{cid}").json()["enrollments"][0]["id"]
    assert client.post(f"/api/enrollments/{eid}/skip", headers=ORIGIN).json() == {"skipped": 1}


def test_campaign_activation_blocked_when_incomplete(client, dataset):  # noqa: F811
    with get_session() as s:
        s.add(Contact(email="x@lead.ma", sequence_code="FIN-IND"))
        s.commit()
        seq_id = s.scalars(select(Sequence.id)).first()
    cid = client.post("/api/campaigns", json={"name": "Incomplète", "sequence_id": seq_id}, headers=ORIGIN).json()["id"]
    rep = client.get(f"/api/campaigns/{cid}/activation").json()
    assert rep["blocked"] and rep["with_problems_count"] >= 1
    assert client.post(f"/api/campaigns/{cid}/activate", json={}, headers=ORIGIN).status_code == 409
    assert client.post(f"/api/campaigns/{cid}/delete", headers=ORIGIN).json()["ok"]


# -------------------------------------------------- réponses, journal, graphique

def test_replies_classify_and_counts(client, dataset):  # noqa: F811
    d = client.get("/api/replies").json()
    assert [i["contact"]["first_name"] for i in d["items"]] == ["Prénom1"]
    assert {f["key"]: f["count"] for f in d["filters"]}["unclassified"] == 1
    mid = d["items"][0]["id"]
    r = client.post(f"/api/replies/{mid}/classify", json={"classification": "later"}, headers=ORIGIN)
    assert r.status_code == 400
    r = client.post(f"/api/replies/{mid}/classify",
                    json={"classification": "later", "callback_on": date.today().isoformat(), "note": "jeudi"},
                    headers=ORIGIN).json()
    assert r["classification"] == "later" and r["note"] == "jeudi"
    assert client.get("/api/replies").json()["items"] == []
    assert client.get("/api/status").json()["to_classify"] == 0


def test_journal_and_activity(client, dataset, monkeypatch):  # noqa: F811
    from datetime import timedelta
    from app.web import api_misc
    from tests.test_m6_dashboard import DAY
    monkeypatch.setattr(api_misc, "utcnow", lambda: DAY + timedelta(days=1))  # jeu de données daté du 04/11/2026
    client.post("/api/exclusions", json={"entry": "a@b.ma"}, headers=ORIGIN)
    j = client.get("/api/journal?q=a").json()
    assert "entities" in j and isinstance(j["items"], list)
    act = client.get("/api/activity?days=30").json()
    assert len(act) == 30 and set(act[0]) == {"day", "sent", "replies"}
    assert sum(a["sent"] for a in act) == 8 and sum(a["replies"] for a in act) == 2


# ------------------------------------------------------------------ réglages

def test_settings_roundtrip_and_validation(client, smtp_ssl, imap_server):
    mb = {"display_name": "Omar Douiri", "email": USER, "smtp_host": "127.0.0.1", "smtp_port": smtp_ssl.port,
          "smtp_security": "ssl", "imap_host": "127.0.0.1", "imap_port": imap_server.port, "username": USER,
          "password": PASSWORD, "watched_folders": ["INBOX"], "signature": "Omar"}
    r = client.post("/api/settings/test-connection", json={**mb, "send_test_email": False}, headers=ORIGIN).json()
    assert r["ok"] and r["sent_folder"] == "INBOX.Sent"
    assert client.put("/api/settings/mailbox", json=mb, headers=ORIGIN).json()["ok"]
    bad = client.put("/api/settings/mailbox", json={**mb, "email": "pas-un-email"}, headers=ORIGIN)
    assert bad.status_code == 422 and "email" in bad.json()["detail"]["errors"]
    st = client.get("/api/settings").json()
    assert st["has_password"] and st["mailbox"]["smtp_port"] == smtp_ssl.port
    sending = {**st["sending"], "daily_cap": 30, "send_windows": [["09:00", "12:00"], ["14:00", "17:00"]]}
    assert client.put("/api/settings/sending", json=sending, headers=ORIGIN).json()["ok"]
    assert client.get("/api/settings").json()["sending"]["daily_cap"] == 30
    bad = client.put("/api/settings/sending", json={**sending, "min_gap_s": 500, "max_gap_s": 100}, headers=ORIGIN)
    assert bad.status_code == 422 and "max_gap_s" in bad.json()["detail"]["errors"]
    assert client.put("/api/settings/test-mode", json={"enabled": False}, headers=ORIGIN).json() == {"test_mode": False}


def test_locked_test_mode_api(client, monkeypatch):
    monkeypatch.setenv("ODDO_FORCE_TEST_MODE", "1")
    assert client.put("/api/settings/test-mode", json={"enabled": False}, headers=ORIGIN).status_code == 409

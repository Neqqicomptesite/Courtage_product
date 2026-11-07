"""V2.2 : modèle Excel, saisie et modification d'un contact à la main, liste « sans réponse
depuis 3 jours ouvrés »."""
import io
from datetime import timedelta

import openpyxl
import pytest
from sqlalchemy import select

from app import importer, scheduling, stats, suppression, template_xlsx, vocab
from app.db import get_session
from app.models import Contact
from tests.test_m6_dashboard import DAY, dataset  # noqa: F401

ORIGIN = {"Origin": "http://testserver"}


# ------------------------------------------------------------------ vocabulaire

@pytest.mark.parametrize("target, family, code", [
    ("Finance & administration", "BTP & immobilier", "FIN-BTP"),
    ("Finance et administration", "Industrie et énergie", "FIN-IND"),  # libellés des blocs
    ("RH", "Santé & pharma", "RH-SANTE"),
    ("dirigeant", "Agroalimentaire", "DIR-AGRO"),                     # début de libellé, casse
    ("FIN", "SRV", "FIN-SRV"),                                         # codes directement
    ("Commercial", "BTP & immobilier", None),                          # cible inconnue
    (None, "BTP & immobilier", None),
])
def test_sequence_code_from_labels(target, family, code):
    assert vocab.sequence_code(target, family) == code


# ------------------------------------------------------------------ modèle Excel

def test_template_is_recognised_without_any_setting(tmp_path, db):
    path = tmp_path / "modele.xlsx"
    path.write_bytes(template_xlsx.build())
    empty = importer.read_table(path)
    assert empty.sheet == "Contacts" and empty.rows == []  # 500 lignes préparées mais vides : rien à importer
    mapping = importer.auto_mapping(empty.headers)
    fields = {m[6:] for m in mapping if m.startswith("field:")}
    customs = [m for m in mapping if m.startswith("custom:")]
    assert {"email", "first_name", "last_name", "company", "job_title", "target_segment", "sector_family",
            "sequence_code", "size_bucket", "wave", "email_reliability", "phone", "website", "linkedin_url",
            "notes", "sector", "kind"} <= fields
    # mêmes clés que le fichier réel d'Omar, déjà utilisées dans ses emails
    assert customs == ["custom:accroche_suggeree", "custom:garanties_a_evoquer_pistes"]

    # Omar remplit une ligne avec les listes déroulantes ; le code (formule) n'a pas de valeur
    # calculée tant qu'Excel n'a pas enregistré : l'import le déduit de la cible et du secteur.
    wb = openpyxl.load_workbook(path)
    ws = wb["Contacts"]
    headers = [c.value for c in ws[1]]
    row = {"Prénom": "Salma", "Email": "Salma@Client.ma", "Segment (cible)": "Finance & administration",
           "Famille de secteur": "Transport & logistique", "Accroche suggérée": "Revue de flotte"}
    for k, v in row.items():
        ws.cell(row=2, column=headers.index(k) + 1, value=v)
    assert str(ws.cell(row=2, column=headers.index("Code séquence (cible × secteur)") + 1).value).startswith("=IF(")
    wb.save(path)
    table = importer.read_table(path)
    with get_session() as s:
        plan = importer.plan_import(s, table, importer.auto_mapping(table.headers))
    (r,) = plan.rows
    assert r.action == "new" and r.email == "salma@client.ma" and not r.warnings
    assert r.values["sequence_code"] == "FIN-TRA" and r.custom == {"accroche_suggeree": "Revue de flotte"}


def test_template_download(client, db):
    r = client.get("/api/contacts/template")
    assert r.status_code == 200 and "Modele_contacts_ODDO.xlsx" in r.headers["content-disposition"]
    wb = openpyxl.load_workbook(io.BytesIO(r.content))
    assert wb.sheetnames == ["Contacts", "Listes", "Mode d'emploi"] and wb["Listes"].sheet_state == "hidden"
    assert len(wb["Contacts"].data_validations.dataValidation) == 8  # + type de contact (V2.3), service et niveau (V2.8)


# ------------------------------------------------------------ saisie à la main

def test_create_contact_by_hand(client, db):
    body = {"first_name": " Salma ", "last_name": "Bennani", "email": "S.Bennani@Client.MA", "company": "Client SARL",
            "target_segment": "Finance & administration", "sector_family": "BTP & immobilier", "wave": "Vague 1",
            "notes": "Rencontrée au salon"}
    r = client.post("/api/contacts", json=body, headers=ORIGIN)
    assert r.status_code == 200 and r.json()["warnings"] == []
    cid = r.json()["id"]
    d = client.get(f"/api/contacts/{cid}").json()
    assert (d["email"], d["first_name"], d["sequence_code"], d["status"]) == ("s.bennani@client.ma", "Salma", "FIN-BTP", "active")
    assert d["notes"] == "Rencontrée au salon" and d["source"].startswith("Saisie manuelle")
    assert sum("Contact créé" in t["title"] for t in d["timeline"]) == 1  # une seule ligne, avec la source

    dup = client.post("/api/contacts", json={"email": "s.bennani@client.ma"}, headers=ORIGIN)
    assert dup.status_code == 409 and dup.json()["detail"]["existing_id"] == cid
    bad = client.post("/api/contacts", json={"email": "pas-un-email"}, headers=ORIGIN)
    assert bad.status_code == 422 and "email" in bad.json()["detail"]["errors"]
    assert client.post("/api/contacts", json={"first_name": "Sans email"}, headers=ORIGIN).status_code == 422
    # vocabulaire renvoyé avec la liste, pour les menus du formulaire
    lst = client.get("/api/contacts").json()
    assert lst["vocab"]["targets"][0]["code"] == "FIN" and "Client SARL" in lst["companies"]


def test_create_refuses_erased_person_and_warns_on_excluded(client, db):
    with get_session() as s:
        suppression.add(s, suppression.email_hash("efface@client.ma"), "Effacement")
        suppression.add(s, "@concurrent.ma", "Exclusion manuelle")
        s.commit()
    assert client.post("/api/contacts", json={"email": "efface@client.ma"}, headers=ORIGIN).status_code == 422
    r = client.post("/api/contacts", json={"email": "x@concurrent.ma"}, headers=ORIGIN).json()
    assert "exclusion" in r["warnings"][0]


def test_update_contact(client, dataset):  # noqa: F811
    cid = dataset["contact_ids"][5]  # pas encore d'email envoyé
    r = client.put(f"/api/contacts/{cid}", json={"job_title": "DAF", "target_segment": "RH",
                                                  "sector_family": "Commerce & distribution",
                                                  "custom": {"accroche_suggeree": "Bonjour"}}, headers=ORIGIN)
    assert set(r.json()["changed"]) == {"job_title", "target_segment", "sector_family", "sequence_code", "accroche_suggeree"}
    d = client.get(f"/api/contacts/{cid}").json()
    assert d["sequence_code"] == "RH-COM" and d["custom"][0]["value"] == "Bonjour"
    assert any("Fiche modifiée" in t["title"] for t in d["timeline"])
    # rien de changé : pas de ligne d'historique en plus
    assert client.put(f"/api/contacts/{cid}", json={"job_title": "DAF"}, headers=ORIGIN).json()["changed"] == []
    # email : modifiable tant qu'aucun email n'a été échangé, jamais vers une adresse déjà prise
    assert client.put(f"/api/contacts/{cid}", json={"email": "nouveau@entreprise5.ma"}, headers=ORIGIN).status_code == 200
    taken = client.put(f"/api/contacts/{cid}", json={"email": "c0@entreprise0.ma"}, headers=ORIGIN)
    assert taken.status_code == 409
    sent = dataset["contact_ids"][2]
    locked = client.put(f"/api/contacts/{sent}", json={"email": "autre@entreprise2.ma"}, headers=ORIGIN)
    assert locked.status_code == 422 and "nouveau contact" in locked.json()["detail"]["errors"]["email"]


# ------------------------------------------------- sans réponse depuis 3 jours ouvrés

def test_followups_count_business_days_and_holidays(dataset):  # noqa: F811
    # c2 : dernier email le mercredi 04/11, une simple réponse d'absence -> reste à relancer.
    # c0/c1 ont répondu, c3 a rebondi, c4 a dit STOP, c5 n'a rien reçu : jamais dans la liste.
    with get_session() as s:
        w = scheduling.SendWindow.from_settings(s)
        assert w.is_business_day(DAY.date() + timedelta(days=2)) is False  # 06/11 Marche verte (férié)

        def names(when):
            return [r["contact"].email for r in stats.followups(s, when, w, 3)]
        assert names(DAY + timedelta(days=5)) == []  # lundi 09/11 : jeudi + lundi = 2 jours ouvrés
        rows = stats.followups(s, DAY + timedelta(days=6), w, 3)  # mardi 10/11 : 3 jours ouvrés
        assert [r["contact"].email for r in rows] == ["c2@entreprise2.ma"]
        assert rows[0]["business_days"] == 3 and rows[0]["step"] == 3
        c2 = s.scalars(select(Contact).where(Contact.email == "c2@entreprise2.ma")).one()
        c2.global_status = "do_not_contact"
        s.flush()
        assert names(DAY + timedelta(days=6)) == []


def test_followups_api(client, dataset, monkeypatch):  # noqa: F811
    from app.web import api
    monkeypatch.setattr(api, "utcnow", lambda: DAY + timedelta(days=6))
    items = client.get("/api/followups").json()
    assert items[0]["contact"]["phone"] == "+212 522 00 00 02" and items[0]["campaign"]["name"] == "Vague 1"
    assert items[0]["next_due_at"] is None  # séquence terminée : c'est à Omar d'appeler
    assert client.get("/api/dashboard").json()["followups"] == {"count": 1, "days": 3}

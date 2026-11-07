"""M2 : import Excel/CSV, contacts, liste d'exclusion, effacement.

Le vrai fichier d'Omar contient des données personnelles : il n'est PAS copié
dans le projet. Un fichier synthétique reproduit ses colonnes et ses pièges.
Pour rejouer le test d'acceptation sur le vrai fichier :
    set ODDO_REAL_LEADS=C:\\chemin\\Leads_ODDO_100leads_segmentes_v2.xlsx
    .venv\\Scripts\\python -m pytest tests/test_m2_import_contacts.py -k real
"""
import os
import re
from pathlib import Path

import openpyxl
import pytest
from sqlalchemy import func, select

from app import contacts_service as cs
from app import importer, suppression
from app.db import get_session
from app.models import Contact, Enrollment, Suppression

ORIGIN = {"Origin": "http://testserver"}
HEADERS = ["#", "Prénom", "Nom", "Poste (LinkedIn)", "Entreprise", "Secteur", "Effectif LinkedIn*",
           "En poste depuis", "Email", "Fiabilité de l'email", "Tél. standard entreprise", "Site web",
           "Profil LinkedIn", "Statut prospection", "Segment (cible)", "Famille de secteur", "Taille*",
           "Vague d'envoi", "Accroche suggérée", "Garanties à évoquer (pistes)",
           "Code séquence (cible × secteur)"]


def _row(n, prenom, email, code="FIN-IND", rel="Bonne (Limadata, via LinkedIn)", phone="+212 522 00 00 00",
         company=None):
    return [n, prenom, "Test", "DAF", company or f"Société {n}", "Industrie", 20, "09/2021", email, rel,
            phone, f"societe{n}.ma", "Voir le profil", "À contacter", "Finance & administration",
            "Industrie & énergie", "Petite (10–49)", "Vague 1", "Revue gratuite", "RC, AT", code]


@pytest.fixture
def leads_xlsx(tmp_path) -> Path:
    wb = openpyxl.Workbook()
    notes = wb.active
    notes.title = "Notes"  # feuille sans contacts en premier : la bonne doit être devinée
    notes.append(["Notes sur le fichier"])
    ws = wb.create_sheet("PME Grand Casablanca")
    ws.append(HEADERS)
    rows = [
        _row(1, "Khaoula", "Khaoula.Rouissi@3smorocco.com"),               # majuscules -> minuscules
        _row(2, "Amine", "amine@kapset.com", code="DIR-BTP", phone="—"),    # « — » = vide
        _row(3, "Sans", "—"),                                               # pas d'email
        _row(4, "Faux", "pas-un-email"),                                    # invalide
        _row(5, "Double", "amine@kapset.com"),                              # doublon dans le fichier
        _row(6, "Perso", "perso@gmail.com", code="RH-SRV", rel="Personnelle (Gmail)"),
        _row(7, "Code", "code@bizarre.ma", code="XXX-IND"),                 # code non reconnu
    ]
    for r in rows:
        ws.append(r)
    for i in range(2, 2 + len(rows)):
        ws.cell(row=i, column=13).hyperlink = f"https://www.linkedin.com/in/profil-{i - 1}"
        email_cell = ws.cell(row=i, column=9)
        if "@" in str(email_cell.value):
            email_cell.hyperlink = f"mailto:{email_cell.value}"
    path = tmp_path / "leads.xlsx"
    wb.save(path)
    return path


def _import_via_ui(client, path: Path):
    with path.open("rb") as fh:
        r = client.post("/contacts/import", files={"file": (path.name, fh)}, headers=ORIGIN,
                        follow_redirects=False)
    assert r.status_code == 303, r.text
    token = r.headers["location"].rsplit("/", 1)[-1]
    page = client.get(f"/contacts/import/{token}")
    assert page.status_code == 200
    selected = dict(re.findall(r'name="(map_\d+)">.*?<option value="([^"]+)"[^>]*selected', page.text, re.S))
    sheet = re.search(r'name="sheet" value="([^"]*)"', page.text).group(1)
    data = {"sheet": sheet, **selected}
    preview = client.post(f"/contacts/import/{token}/preview", data=data, headers=ORIGIN)
    assert preview.status_code == 200, preview.text
    done = client.post(f"/contacts/import/{token}/commit", data=data, headers=ORIGIN, follow_redirects=False)
    assert done.status_code == 303
    return preview.text, done.headers["location"]


# ---------------------------------------------------------------- lecture / plan

def test_read_table_finds_sheet_header_and_links(leads_xlsx):
    t = importer.read_table(leads_xlsx)
    assert t.sheet == "PME Grand Casablanca"
    assert t.header_row == 1 and len(t.rows) == 7
    assert t.rows[0][12].value == "Voir le profil"
    assert t.rows[0][12].link == "https://www.linkedin.com/in/profil-1"


def test_auto_mapping_matches_real_headers():
    m = dict(zip(HEADERS, importer.auto_mapping(HEADERS)))
    assert m["#"] == "ignore"
    assert m["Email"] == "field:email"
    assert m["Code séquence (cible × secteur)"] == "field:sequence_code"
    assert m["Taille*"] == "field:size_bucket"
    assert m["Profil LinkedIn"] == "field:linkedin_url"
    assert m["Effectif LinkedIn*"] == "custom:effectif_linkedin"
    assert m["Accroche suggérée"] == "custom:accroche_suggeree"
    assert importer.validate_mapping(list(m.values())) == []


def test_plan_classifies_rows(db, leads_xlsx):
    t = importer.read_table(leads_xlsx)
    with get_session() as s:
        plan = importer.plan_import(s, t, importer.auto_mapping(t.headers))
    assert len(plan.of("new")) == 4
    reasons = sorted(r.reason.split(" :")[0] for r in plan.of("ignore"))
    assert reasons == ["Doublon de la ligne 3 dans le fichier", "Email invalide", "Pas d'email"]
    first = plan.rows[0]
    assert first.email == "khaoula.rouissi@3smorocco.com"
    assert first.values["linkedin_url"] == "https://www.linkedin.com/in/profil-1"
    assert "phone" not in plan.rows[1].values  # « — »
    assert [r.email for r in plan.warned] == ["code@bizarre.ma"]


def test_mapping_without_email_is_rejected():
    assert "Email" in importer.validate_mapping(["field:first_name", "ignore"])[0]


def test_csv_windows1252_semicolon(db, tmp_path):
    path = tmp_path / "contacts.csv"
    path.write_bytes("Prénom;Nom;Email;Entreprise\nRéda;Benani;reda@exemple.ma;Société Générale\n"
                     .encode("cp1252"))
    t = importer.read_table(path)
    assert t.headers == ["Prénom", "Nom", "Email", "Entreprise"]
    with get_session() as s:
        plan = importer.plan_import(s, t, importer.auto_mapping(t.headers))
    assert plan.rows[0].values["first_name"] == "Réda"
    assert plan.rows[0].values["company"] == "Société Générale"


def test_csv_utf8_with_bom_and_commas(tmp_path):
    path = tmp_path / "c.csv"
    path.write_bytes("\ufeffEmail,Prénom\nx@y.ma,Élodie\n".encode("utf-8"))
    t = importer.read_table(path)
    assert t.headers == ["Email", "Prénom"] and t.rows[0][1].value == "Élodie"


# ------------------------------------------------------------------- via l'écran

def test_import_through_ui_then_reimport_without_duplicates(client, leads_xlsx):
    preview, location = _import_via_ui(client, leads_xlsx)
    assert "nouveaux" in preview and "Doublon de la ligne 3" in preview
    assert "non reconnu" in preview  # avertissement code séquence
    assert location == "/contacts?imported=4-0-3"
    with get_session() as s:
        assert s.scalar(select(func.count(Contact.id))) == 4
        k = s.scalars(select(Contact).where(Contact.email == "khaoula.rouissi@3smorocco.com")).one()
        assert k.linkedin_url == "https://www.linkedin.com/in/profil-1"
        assert k.sequence_code == "FIN-IND"
        assert k.custom["accroche_suggeree"] == "Revue gratuite"
        assert k.source.startswith("leads.xlsx – importé le ")
        k.notes = "Rappeler en janvier"
        s.commit()

    _, location = _import_via_ui(client, leads_xlsx)
    assert location == "/contacts?imported=0-4-3"
    with get_session() as s:
        assert s.scalar(select(func.count(Contact.id))) == 4  # aucun doublon
        k = s.scalars(select(Contact).where(Contact.email == "khaoula.rouissi@3smorocco.com")).one()
        assert k.notes == "Rappeler en janvier"  # les notes ne sont pas écrasées
    # le fichier envoyé n'est pas conservé
    from app.paths import data_dir
    assert list((data_dir() / "imports").glob("*")) == []


def test_import_rejects_other_formats_and_bad_tokens(client, tmp_path):
    p = tmp_path / "x.pdf"
    p.write_bytes(b"%PDF")
    with p.open("rb") as fh:
        r = client.post("/contacts/import", files={"file": ("x.pdf", fh)}, headers=ORIGIN)
    assert "Format non pris en charge" in r.text
    assert client.get("/contacts/import/..%2F..%2Foddo").status_code == 404
    assert client.get("/contacts/import/0123456789abcdef").status_code == 404


def test_list_filters_and_search(client, leads_xlsx):
    _import_via_ui(client, leads_xlsx)
    page = client.get("/contacts").text
    assert "4 contact(s) affiché(s) sur 4" in page
    assert "1 contact(s) affiché(s)" in client.get("/contacts?reliability=Personnelle").text
    assert "1 contact(s) affiché(s)" in client.get("/contacts?sequence_code=DIR-BTP").text
    assert "3 contact(s) affiché(s)" in client.get("/contacts?reliability=Bonne").text
    assert "1 contact(s) affiché(s)" in client.get("/contacts?q=kapset").text
    assert "0 contact(s) affiché(s)" in client.get("/contacts?reliability=Autre").text


def test_reliability_category():
    assert cs.reliability_category("Bonne (Findymail)") == "Bonne"
    assert cs.reliability_category("À vérifier – domaine x ≠ y") == "À vérifier"
    assert cs.reliability_category("Générique (Gmail)") == "Générique"
    assert cs.reliability_category(None) == "Autre"


# --------------------------------------------------- fiche, exclusion, effacement

def _contact_id(email):
    with get_session() as s:
        return s.scalars(select(Contact.id).where(Contact.email == email)).one()


def test_contact_page_notes_and_status_actions(client, leads_xlsx):
    _import_via_ui(client, leads_xlsx)
    cid = _contact_id("amine@kapset.com")
    page = client.get(f"/contacts/{cid}").text
    assert "Voir le profil" in page and "Contact créé – source : leads.xlsx" in page
    assert "Accroche suggérée" in page  # libellé d'origine, accents compris

    client.post(f"/contacts/{cid}/notes", data={"notes": "Intéressé par la flotte auto"}, headers=ORIGIN)
    client.post(f"/contacts/{cid}/do-not-contact", headers=ORIGIN)
    page = client.get(f"/contacts/{cid}").text
    assert "Intéressé par la flotte auto" in page
    assert "Statut → Ne plus contacter" in page
    client.post(f"/contacts/{cid}/reactivate", headers=ORIGIN)
    with get_session() as s:
        assert s.get(Contact, cid).global_status == "active"


def test_unsubscribed_contact_cannot_be_reactivated(client, leads_xlsx):
    _import_via_ui(client, leads_xlsx)
    cid = _contact_id("amine@kapset.com")
    with get_session() as s:
        s.get(Contact, cid).global_status = "unsubscribed"
        s.commit()
    r = client.post(f"/contacts/{cid}/reactivate", headers=ORIGIN)
    assert "définitive" in r.text
    with get_session() as s:
        assert s.get(Contact, cid).global_status == "unsubscribed"


def test_domain_exclusion_flags_contacts_and_import(client, leads_xlsx):
    _import_via_ui(client, leads_xlsx)
    r = client.post("/contacts/exclusions/add", data={"entry": "KAPSET.com", "note": "client existant"},
                    headers=ORIGIN)
    assert "@kapset.com" in r.text or "kapset.com" in r.text
    assert "1 contact(s) passé(s)" in r.text
    with get_session() as s:
        assert s.get(Contact, _contact_id("amine@kapset.com")).global_status == "do_not_contact"
        assert suppression.is_suppressed_db(s, "autre.personne@kapset.com")
    # au ré-import, l'adresse est signalée
    preview, _ = _import_via_ui(client, leads_xlsx)
    assert "dans la liste d&#39;exclusion" in preview or "dans la liste d'exclusion" in preview
    assert "Ligne 3 : amine@kapset.com" in preview


def test_invalid_exclusion_entry(client):
    r = client.post("/contacts/exclusions/add", data={"entry": "pas un domaine"}, headers=ORIGIN)
    assert "Saisissez une adresse" in r.text


def test_stop_entries_cannot_be_removed(client, db):
    with get_session() as s:
        suppression.add(s, "stop@exemple.ma", "STOP reçu")
        s.commit()
        sid = s.scalars(select(Suppression.id)).one()
    assert client.post(f"/contacts/exclusions/{sid}/delete", headers=ORIGIN).status_code == 403


def test_erase_contact_keeps_only_hash(client, leads_xlsx):
    _import_via_ui(client, leads_xlsx)
    cid = _contact_id("khaoula.rouissi@3smorocco.com")
    r = client.post(f"/contacts/{cid}/erase", data={"confirm": "non"}, headers=ORIGIN)
    assert "Tapez EFFACER" in r.text
    r = client.post(f"/contacts/{cid}/erase", data={"confirm": "EFFACER"}, headers=ORIGIN)
    assert "effacées définitivement" in r.text
    with get_session() as s:
        assert s.get(Contact, cid) is None
        entries = list(s.scalars(select(Suppression.email_or_domain)))
        assert entries == [suppression.email_hash("khaoula.rouissi@3smorocco.com")]
        assert not any("khaoula" in e for e in entries)
    # Ré-importer le fichier ne doit PAS recréer ses données.
    preview, _ = _import_via_ui(client, leads_xlsx)
    assert "Contact effacé à sa demande" in preview
    with get_session() as s:
        assert s.scalars(select(Contact).where(Contact.email.like("khaoula%"))).first() is None


def test_remove_from_campaign_stops_enrollment(client, leads_xlsx):
    from app.models import Campaign, Mailbox, Sequence
    _import_via_ui(client, leads_xlsx)
    cid = _contact_id("amine@kapset.com")
    with get_session() as s:
        mb = Mailbox(display_name="O", email="o@oddo.ma")
        s.add(mb)
        s.flush()
        camp = Campaign(name="Test", mailbox_id=mb.id, sequence_id=s.scalars(select(Sequence.id)).first())
        s.add(camp)
        s.flush()
        enr = Enrollment(campaign_id=camp.id, contact_id=cid, status="waiting")
        s.add(enr)
        s.commit()
        eid = enr.id
    assert "Test" in client.get(f"/contacts/{cid}").text
    client.post(f"/contacts/{cid}/enrollments/{eid}/remove", headers=ORIGIN)
    with get_session() as s:
        e = s.get(Enrollment, eid)
        assert (e.status, e.stop_reason) == ("stopped", "manual_removed")


# --------------------------------------------- acceptation M2 sur le vrai fichier

@pytest.mark.skipif(not os.environ.get("ODDO_REAL_LEADS"), reason="ODDO_REAL_LEADS non défini")
def test_real_file_acceptance(client):
    path = Path(os.environ["ODDO_REAL_LEADS"])
    _, location = _import_via_ui(client, path)
    assert location == "/contacts?imported=100-0-0"
    with get_session() as s:
        contacts = list(s.scalars(select(Contact)))
        assert len(contacts) == 100
        assert all(c.linkedin_url and c.linkedin_url.startswith("https://www.linkedin.com/") for c in contacts)
        assert all(importer.check_sequence_code(c.sequence_code) is None for c in contacts)
    _, location = _import_via_ui(client, path)
    assert location == "/contacts?imported=0-100-0"
    with get_session() as s:
        assert s.scalar(select(func.count(Contact.id))) == 100

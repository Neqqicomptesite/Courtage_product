"""V2.3 : entreprises, types de contacts (seuls les prospects sont prospectés), ajout d'un
seul contact à une campagne, et reprise des données existantes par la migration."""
from datetime import timedelta

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from sqlalchemy import select

from app import campaigns_service as camp_svc
from app import companies_service as co
from app.db import get_session
from app.models import Campaign, Company, Contact, Enrollment, Sequence
from app.paths import PROJECT_DIR
from app.timeutil import utcnow

ORIGIN = {"Origin": "http://testserver"}


@pytest.mark.parametrize("a, b", [
    ("SANLAM Maroc S.A.", "Sanlam"), ("Kapset Group", "Kapset"), ("Société Générale Maroc", "Societe generale"),
    ("Wafa Assurance SA", "wafa assurance"), ("AXA Assurance Maroc", "Axa assurance"), ("3S Morocco", "3S"),
])
def test_company_key_groups_spellings(a, b):
    assert co.company_key(a) == co.company_key(b)


def test_company_key_keeps_different_companies_apart():
    assert co.company_key("Wafa Assurance") != co.company_key("Wafa Immobilier")
    assert co.company_key("Maroc Telecom") == "telecom"  # « maroc » seul retiré, le reste distingue
    assert co.company_key("Groupe") == "groupe"           # nom fait uniquement de mots « bruit » : on le garde


# ---------------------------------------------------------------- migration

def _insert(conn, table: str, **values):
    """Insère une ligne en remplissant toute colonne obligatoire non fournie (schéma 0004)."""
    for _, name, typ, notnull, default, pk in conn.execute(sa.text(f"PRAGMA table_info({table})")):
        if name in values or not notnull or default is not None or pk:
            continue
        typ = typ.upper()
        values[name] = 0 if "INT" in typ or "BOOL" in typ else ("2026-11-01 09:00:00.000000" if "DATETIME" in typ else "x")
    cols = ", ".join(values)
    conn.execute(sa.text(f"INSERT INTO {table} ({cols}) VALUES ({', '.join(':' + k for k in values)})"), values)


def test_migration_groups_existing_contacts_and_keeps_history(tmp_path):
    """Base en 0004 avec contacts, inscriptions et messages -> 0005 : rien n'est perdu
    (la recréation de la table contact ne doit PAS déclencher les suppressions en cascade)."""
    url = f"sqlite:///{tmp_path / 'm.db'}"
    cfg = Config(str(PROJECT_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(PROJECT_DIR / "migrations"))
    cfg.attributes["db_url"] = url
    command.upgrade(cfg, "2ada5cec1381")
    eng = sa.create_engine(url)
    t = "2026-11-01 09:00:00.000000"
    with eng.begin() as c:
        c.execute(sa.text("PRAGMA foreign_keys=ON"))
        rows = [("a@sanlam.ma", "SANLAM Maroc"), ("b@sanlam.ma", "Sanlam"), ("c@gmail.com", "Sanlam S.A."),
                ("d@kapset.ma", "Kapset Group"), ("e@x.ma", None)]
        for i, (email, comp) in enumerate(rows, 1):
            c.execute(sa.text("INSERT INTO contact (id, email, company, custom, global_status, notes, created_at, updated_at) "
                              "VALUES (:i, :e, :c, '{}', 'active', '', :t, :t)"), {"i": i, "e": email, "c": comp, "t": t})
        _insert(c, "sequence", id=1, name="S")
        _insert(c, "mailbox", id=1, smtp_security="ssl", watched_folders="[]")
        _insert(c, "campaign", id=1, sequence_id=1, mailbox_id=1, filters="{}", status="active")
        _insert(c, "enrollment", id=1, campaign_id=1, contact_id=1, current_step=2, status="waiting")
        _insert(c, "message", contact_id=1, enrollment_id=1, direction="out", subject="Bonjour", sent_at=t)
    command.upgrade(cfg, "head")
    with eng.connect() as c:
        assert c.execute(sa.text("SELECT count(*) FROM enrollment")).scalar() == 1
        assert c.execute(sa.text("SELECT count(*) FROM message")).scalar() == 1
        comps = c.execute(sa.text("SELECT name, domain, kind FROM company ORDER BY name")).all()
        assert comps == [("Kapset Group", "kapset.ma", "prospect"), ("SANLAM Maroc", "sanlam.ma", "prospect")]
        linked = dict(c.execute(sa.text("SELECT email, company FROM contact")).all())
        assert linked["c@gmail.com"] == "SANLAM Maroc" and linked["e@x.ma"] is None  # une seule orthographe
        assert set(c.execute(sa.text("SELECT DISTINCT kind FROM contact")).scalars()) == {"prospect"}
    command.downgrade(cfg, "2ada5cec1381")  # retour arrière possible
    eng.dispose()


# ---------------------------------------------------------------- API entreprises

def _contact(client, **kw):
    r = client.post("/api/contacts", json=kw, headers=ORIGIN)
    assert r.status_code == 200, r.text
    return r.json()["id"]


def test_contacts_are_linked_and_company_page(client, db):
    a = _contact(client, email="nadia@sanlam.ma", first_name="Nadia", job_title="Gestionnaire sinistres", company="Sanlam")
    b = _contact(client, email="karim@sanlam.ma", first_name="Karim", company="SANLAM Maroc S.A.")
    lst = client.get("/api/companies").json()
    assert lst["total"] == 1 and lst["items"][0]["people"] == 2 and lst["items"][0]["domain"] == "sanlam.ma"
    cid = lst["items"][0]["id"]
    assert client.get(f"/api/contacts/{b}").json()["company"] == "Sanlam"  # orthographe unique
    # « je veux écrire au gestionnaire de Sanlam » : la recherche trouve l'entreprise par le poste
    assert [i["name"] for i in client.get("/api/companies?q=gestionnaire").json()["items"]] == ["Sanlam"]
    d = client.get(f"/api/companies/{cid}").json()
    assert [p["first_name"] for p in d["people"]] == ["Karim", "Nadia"] or len(d["people"]) == 2
    assert client.get(f"/api/contacts/{a}").json()["company_ref"] == {"id": cid, "name": "Sanlam", "kind": "prospect"}
    assert client.get(f"/api/contacts?company_id={cid}").json()["items"].__len__() == 2

    # type assureur : s'applique aux deux personnes ; un nouveau venu en hérite
    assert client.put(f"/api/companies/{cid}", json={"kind": "insurer", "phone": "0522"}, headers=ORIGIN).status_code == 200
    assert {client.get(f"/api/contacts/{i}").json()["kind"] for i in (a, b)} == {"insurer"}
    c = _contact(client, email="new@sanlam.ma", company="Sanlam")
    assert client.get(f"/api/contacts/{c}").json()["kind"] == "insurer"
    assert client.get("/api/companies?kind=insurer").json()["kinds"][2]["count"] == 1


def test_rename_merge_delete(client, db):
    _contact(client, email="x@kapset.ma", company="Kapset")
    _contact(client, email="y@kapsett.ma", company="Kapsett")  # faute de frappe : autre fiche
    items = {i["name"]: i["id"] for i in client.get("/api/companies").json()["items"]}
    clash = client.put(f"/api/companies/{items['Kapsett']}", json={"name": "Kapset Group"}, headers=ORIGIN)
    assert clash.status_code == 409 and clash.json()["detail"]["existing_id"] == items["Kapset"]
    r = client.post(f"/api/companies/{items['Kapsett']}/merge", json={"into_id": items["Kapset"]}, headers=ORIGIN)
    assert r.json()["moved"] == 1
    assert client.get(f"/api/companies/{items['Kapset']}").json()["people"].__len__() == 2
    client.put(f"/api/companies/{items['Kapset']}", json={"name": "Kapset Group"}, headers=ORIGIN)
    assert {p["company"] for p in client.get("/api/contacts").json()["items"]} == {"Kapset Group"}
    assert client.delete(f"/api/companies/{items['Kapset']}", headers=ORIGIN).status_code == 409
    empty = client.post("/api/companies", json={"name": "Wafa Assurance", "kind": "insurer"}, headers=ORIGIN).json()["id"]
    assert client.post("/api/companies", json={"name": "WAFA ASSURANCE SA"}, headers=ORIGIN).status_code == 409
    assert client.delete(f"/api/companies/{empty}", headers=ORIGIN).status_code == 200


# ------------------------------------------- types : protection des non-prospects

@pytest.fixture
def running(client, db):
    """Une campagne active (séquence par défaut) et trois prospects d'une même entreprise."""
    from app import sequences_service as ss
    from app.models import Mailbox
    with get_session() as s:
        s.add(Mailbox(display_name="Omar", email="o.douiri@oddo.ma", smtp_host="127.0.0.1", smtp_port=465,
                      smtp_security="ssl", imap_host="127.0.0.1", imap_port=993, username="o", watched_folders=["INBOX"],
                      signature=""))
        seq = ss.create_sequence(s, "Séquence")
        for st in ss.steps_of(s, seq):
            st.body_template = "Bonjour {{ prenom }}"
            for v in ss.variants_of(s, st).values():
                v.subject_template = "Vos contrats"
        s.flush()
        camp = Campaign(name="Vague", sequence_id=seq.id, mailbox_id=1, filters={}, status="active")
        s.add(camp)
        s.commit()
        camp_id, seq_id = camp.id, seq.id
    ids = [_contact(client, email=f"p{i}@client.ma", first_name=f"P{i}", company="Client SA") for i in range(3)]
    return {"camp": camp_id, "seq": seq_id, "ids": ids}


def test_enroll_one_contact(client, running):
    cid = running["ids"][0]
    r = client.post(f"/api/campaigns/{running['camp']}/enroll", json={"contact_id": cid}, headers=ORIGIN)
    assert r.status_code == 200
    again = client.post(f"/api/campaigns/{running['camp']}/enroll", json={"contact_id": cid}, headers=ORIGIN)
    assert again.status_code == 409 and "déjà" in again.json()["detail"]["message"]
    d = client.get(f"/api/contacts/{cid}").json()
    assert d["enrollments"][0]["campaign"]["name"] == "Vague"
    assert any("Ajouté à la campagne" in t["title"] for t in d["timeline"])
    assert [c["name"] for c in client.get("/api/campaigns-open").json()] == ["Vague"]


def test_non_prospects_never_enter_or_stay_in_campaigns(client, running):
    p0, p1, p2 = running["ids"]
    client.post(f"/api/campaigns/{running['camp']}/enroll", json={"contact_id": p0}, headers=ORIGIN)
    # un seul contact passe client : refusé dans une campagne
    client.put(f"/api/contacts/{p1}", json={"kind": "client"}, headers=ORIGIN)
    r = client.post(f"/api/campaigns/{running['camp']}/enroll", json={"contact_id": p1}, headers=ORIGIN)
    assert r.status_code == 409 and "prospects" in r.json()["detail"]["message"]
    # l'entreprise devient cliente : la séquence en cours de p0 s'arrête aussitôt
    comp_id = client.get(f"/api/contacts/{p0}").json()["company_ref"]["id"]
    assert client.put(f"/api/companies/{comp_id}", json={"kind": "client"}, headers=ORIGIN).json()["stopped"] == 1
    with get_session() as s:
        enr = s.scalars(select(Enrollment).where(Enrollment.contact_id == p0)).one()
        assert (enr.status, enr.stop_reason) == ("stopped", "kind_client")
        # et une campagne lancée par filtres les exclut avec une raison lisible
        camp = Campaign(name="Autre", sequence_id=running["seq"], mailbox_id=1, filters={}, status="draft")
        s.add(camp)
        s.flush()
        reasons = {c.contact.id: c.excluded for c in camp_svc.candidates(s, camp, check_render=False)}
        assert reasons[p2] == "Client : jamais prospecté"
    # le compteur de l'assistant ne compte que les prospects
    assert client.get("/api/contacts/count").json() == {"matching": 3, "active": 0, "protected": 3}


def test_engine_rechecks_kind_before_sending(client, running):
    from app import engine
    p0 = running["ids"][0]
    client.post(f"/api/campaigns/{running['camp']}/enroll", json={"contact_id": p0}, headers=ORIGIN)
    with get_session() as s:
        c = s.get(Contact, p0)
        c.kind = "partner"  # changé directement en base, sans passer par le service
        s.commit()
        enr = s.scalars(select(Enrollment).where(Enrollment.contact_id == p0)).one()
        assert engine._recheck(s, enr, c) == "kind_partner"


def test_enroll_refuses_incomplete_email_and_asks_for_overlap(client, running):
    p0 = running["ids"][0]
    with get_session() as s:
        from app import sequences_service as ss
        seq = s.get(Sequence, running["seq"])
        ss.steps_of(s, seq)[0].body_template = "Bonjour {{ custom.inexistant }}"
        other = Campaign(name="Autre", sequence_id=running["seq"], mailbox_id=1, filters={}, status="active")
        s.add(other)
        s.commit()
        other_id = other.id
    r = client.post(f"/api/campaigns/{running['camp']}/enroll", json={"contact_id": p0}, headers=ORIGIN)
    assert r.status_code == 409 and r.json()["detail"]["problems"]
    with get_session() as s:
        seq = s.get(Sequence, running["seq"])
        from app import sequences_service as ss
        ss.steps_of(s, seq)[0].body_template = "Bonjour"
        s.commit()
    assert client.post(f"/api/campaigns/{other_id}/enroll", json={"contact_id": p0}, headers=ORIGIN).status_code == 200
    busy = client.post(f"/api/campaigns/{running['camp']}/enroll", json={"contact_id": p0}, headers=ORIGIN)
    assert busy.status_code == 409 and busy.json()["detail"]["overlap"] == ["Autre"]
    forced = client.post(f"/api/campaigns/{running['camp']}/enroll", json={"contact_id": p0, "overlap": True}, headers=ORIGIN)
    assert forced.status_code == 200


def test_import_type_column_and_inheritance(client, db, tmp_path):
    from openpyxl import Workbook
    from app import importer
    with get_session() as s:
        co.get_or_create(s, "Sanlam", "insurer")
        s.commit()
    wb = Workbook()
    ws = wb.active
    ws.append(["Email", "Entreprise", "Type de contact"])
    ws.append(["g@sanlam.ma", "SANLAM Maroc", None])          # hérite : assureur
    ws.append(["c@client.ma", "Client SA", "Client"])
    ws.append(["z@zz.ma", "ZZ", "Fournisseur"])                # inconnu : prospect + avertissement
    path = tmp_path / "f.xlsx"
    wb.save(path)
    table = importer.read_table(path)
    with get_session() as s:
        plan = importer.plan_import(s, table, importer.auto_mapping(table.headers))
        assert "Fournisseur" in plan.rows[2].warnings[0]
        importer.apply_plan(s, plan, "test")
        s.commit()
        kinds = {c.email: (c.kind, c.company) for c in s.scalars(select(Contact))}
    assert kinds == {"g@sanlam.ma": ("insurer", "Sanlam"), "c@client.ma": ("client", "Client SA"),
                     "z@zz.ma": ("prospect", "ZZ")}


def test_kind_counts_and_followup_setting(client, db):  # V2.7
    _contact(client, email="a@sanlam.ma", company="Sanlam", kind="insurer")
    _contact(client, email="b@x.ma", company="X")
    assert client.get("/api/contacts").json()["kind_counts"] == {"insurer": 1, "prospect": 1}
    assert client.get("/api/settings").json()["sending"]["followup_days"] == 3

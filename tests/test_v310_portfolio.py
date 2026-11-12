"""V3.10 : portefeuille clients (export DIAMM) : import consolidé, analyse, vente croisée, appels."""
from datetime import date, timedelta

from sqlalchemy import select

from app import portfolio as pf
from app.db import get_session
from app.models import Contact, ContactList, PortfolioClient, PortfolioContract
from app.timeutil import to_local, utcnow
from tests.test_m4_engine import ORIGIN

HEAD = "CLIENT;Particulier;TELEP1;TELEP2;FAX;Responsable;AEMAIL;POLICE;COMPAGNIE;CATEGORIE;BRANCHE;MISE_EN_DE;FERME_RENO;DATE_RESI;DATE_MED;Resiliee;Flotte"
ROWS = [
    # particulier, Auto seulement, 2 lignes (auto + assistance voyage), téléphone avec prénom
    " BENNANI KARIM;O;;0661000001- SALMA;;;;P-1;AXA ASSURANCE MAROC;AUTOMOBILE;AUTO PARTICULIERS;N;N;;;N;N",
    "BENNANI  KARIM;O;;;;;;P-2;MAROC ASSISTANCE INTERNATIONALE;ASSISTANCE;INJAD MONDE;N;N;;;N;N",
    # particulier avec email, Auto + Habitation
    "TAZI NADIA;O;0522000002;;;;nadia.tazi@exemple.ma;P-3;RMA ASSURANCE;AUTOMOBILE;AUTO PARTICULIERS;N;N;;;N;N",
    "TAZI NADIA;O;0522000002;;;;nadia.tazi@exemple.ma;P-4;RMA ASSURANCE;RISQUES DIVERS;MULTIRISQUE HABITATIONS;N;N;;;N;N",
    # entreprise : AT + flotte, RC résiliée
    "STE ATLAS BETON SARL;N;0522000003;;;DE LA PART DE M. ALAOUI;contact@atlasbeton.ma;P-5;WAFA ASSURANCE;ACCIDENTS DU TRAVAIL;ACCIDENTS DE TRAVAIL;N;O;;;N;N",
    "STE ATLAS BETON SARL;N;0522000003;;;DIRECTEUR M. ALAOUI;contact@atlasbeton.ma;P-6;WAFA ASSURANCE;AUTOMOBILE;AUTO FLOTTE;N;N;;;N;O",
    "STE ATLAS BETON SARL;N;0522000003;;;;contact@atlasbeton.ma;P-7;AXA ASSURANCE MAROC;RESPONSABILITES CIVILES;RC. EXPLOITATION;N;N;44894;;O;N",
    # entreprise sans email ni téléphone, branche inconnue
    "SAHEL NEGOCE;N;;;;;;P-8;SANAD;RISQUES DIVERS;BRANCHE INVENTEE;N;N;;;N;N",
    # quasi-doublon (forme juridique)
    "ATLAS BETON;N;;;;;;P-9;SANAD;INCENDIE;INCENDIE / EXPLOSION;N;N;;;N;N",
    # ligne sans police : ignorée
    "SANS POLICE;O;;;;;;;AXA;AUTOMOBILE;AUTO PARTICULIERS;N;N;;;N;N",
]


def _file(tmp_path, rows=ROWS, name="portefeuille.csv"):
    p = tmp_path / name
    p.write_text("\n".join([HEAD, *rows]), encoding="utf-8")
    return p


def _import(tmp_path, rows=ROWS):
    with get_session() as s:
        rep = pf.import_file(s, _file(tmp_path, rows))
        s.commit()
        return rep


def test_import_consolidates_clients_and_contracts(db, tmp_path):
    rep = _import(tmp_path)
    assert (rep.rows, rep.skipped, rep.clients_new, rep.contracts_new) == (10, 1, 5, 9)
    assert (rep.particuliers, rep.pros, rep.with_email, rep.with_phone) == (2, 3, 2, 3)
    assert rep.unknown_branches == ["BRANCHE INVENTEE"] and rep.duplicates == [["ATLAS BETON", "STE ATLAS BETON SARL"]]
    with get_session() as s:
        k = s.scalars(select(PortfolioClient).where(PortfolioClient.key == "BENNANI KARIM")).one()
        assert k.segment == "particulier" and k.phones == [{"number": "0661000001", "label": "Salma"}] and k.email is None
        a = s.scalars(select(PortfolioClient).where(PortfolioClient.key == "STE ATLAS BETON SARL")).one()
        assert a.segment == "pro" and "DE LA PART DE M. ALAOUI" in a.note and a.email == "contact@atlasbeton.ma"
        rc = s.scalars(select(PortfolioContract).where(PortfolioContract.policy == "P-7")).one()
        assert rc.cancelled and rc.cancelled_on == date(2022, 11, 29) and rc.family == "RC entreprise"
        flotte = s.scalars(select(PortfolioContract).where(PortfolioContract.policy == "P-6")).one()
        assert flotte.fleet and flotte.family == "Flotte auto"
        assert s.scalars(select(PortfolioContract).where(PortfolioContract.policy == "P-8")).one().family == "Autres risques"
        # avec email : contact « client » de l'appli, au nom présentable
        c = s.scalars(select(Contact).where(Contact.email == "contact@atlasbeton.ma")).one()
        assert c.kind == "client" and c.company == "Atlas Beton SARL" and a.contact_id == c.id


def test_reimport_updates_without_duplicates_and_keeps_noted_email(db, tmp_path):
    _import(tmp_path)
    with get_session() as s:
        k = s.scalars(select(PortfolioClient).where(PortfolioClient.key == "BENNANI KARIM")).one()
        pf.set_email(s, k, "karim.bennani@exemple.ma")      # noté pendant un appel
        s.commit()
    rep = _import(tmp_path, ROWS + ["BENNANI KARIM;O;;;;;;P-10;AXA ASSURANCE MAROC;RISQUES DIVERS;MULTIRISQUE HABITATIONS;N;N;;;N;N"])
    assert (rep.clients_new, rep.clients_updated, rep.contracts_new, rep.contracts_updated) == (0, 5, 1, 9)
    with get_session() as s:
        assert s.query(PortfolioClient).count() == 5 and s.query(PortfolioContract).count() == 10
        k = s.scalars(select(PortfolioClient).where(PortfolioClient.key == "BENNANI KARIM")).one()
        assert k.email == "karim.bennani@exemple.ma" and k.contact_id


def test_prospect_with_same_email_becomes_client(db, tmp_path):
    from app import contacts_service as cs
    with get_session() as s:
        cs.create_contact(s, {"email": "nadia.tazi@exemple.ma", "first_name": "Nadia", "kind": "prospect"}, "test")
        s.commit()
    rep = _import(tmp_path)
    assert rep.contacts_linked == 1 and rep.prospects_now_clients == 1
    with get_session() as s:
        assert s.scalars(select(Contact).where(Contact.email == "nadia.tazi@exemple.ma")).one().kind == "client"


def test_summary_and_opportunities(db, tmp_path):
    _import(tmp_path)
    with get_session() as s:
        d = pf.summary(s)
    assert (d["clients"], d["active_clients"], d["contracts"], d["cancelled"]) == (5, 5, 8, 1)
    assert d["segments"]["particulier"]["count"] == 2 and d["segments"]["pro"]["mono"] == 2
    opp = {o["key"]: o for o in d["opportunities"]}
    assert opp["part-auto-habitation"]["count"] == 1 and opp["part-auto-habitation"]["phone"] == 1  # Karim
    assert opp["pro-rc"]["count"] == 3 and opp["pro-rc"]["email"] == 1                               # RC résiliée = manquante
    assert opp["pro-at-sante"]["count"] == 1
    fam = {f["family"]: f for f in d["families"]}
    assert fam["Auto"]["particulier"] == {"clients": 2, "pct": 100}


def test_api_list_calls_callbacks_and_bell(client, db, tmp_path):
    p = _file(tmp_path)
    with p.open("rb") as f:
        r = client.post("/api/portfolio/import", files={"file": ("portefeuille.csv", f, "text/csv")}, headers=ORIGIN)
    assert r.status_code == 200, r.text
    rows = client.get("/api/portfolio/clients", params={"rule": "pro-rc"}).json()
    assert rows["total"] == 3 and rows["email"] == 1
    # liste pour campagne : seulement ceux qui ont un email
    out = client.post("/api/portfolio/list", json={"name": "Pros sans RC", "rule": "pro-rc"}, headers=ORIGIN).json()
    assert (out["added"], out["without_email"]) == (1, 2)
    with get_session() as s:
        assert s.get(ContactList, out["list_id"]).name == "Pros sans RC"
    # appel : intéressé, email noté -> joignable par email ; puis rappel prévu
    sahel = next(x for x in rows["items"] if x["name"] == "SAHEL NEGOCE")
    d = client.post(f"/api/portfolio/clients/{sahel['id']}/calls", json={"outcome": "interested", "rule": "pro-rc",
                    "note": "Veut un devis RC", "email": "gerant@sahel.ma"}, headers=ORIGIN).json()
    assert d["email"] == "gerant@sahel.ma" and d["contact_id"] and d["last_call"]["label"] == "Intéressé"
    assert client.post(f"/api/portfolio/clients/{sahel['id']}/calls", json={"outcome": "callback"}, headers=ORIGIN).status_code == 422
    today = to_local(utcnow()).date()
    client.post(f"/api/portfolio/clients/{sahel['id']}/calls", json={"outcome": "callback", "callback_on": today.isoformat(),
                "note": "Rappeler après 15 h", "rule": "pro-rc"}, headers=ORIGIN)
    cbs = client.get("/api/portfolio/callbacks").json()["items"]
    assert [c["client"]["name"] for c in cbs] == ["SAHEL NEGOCE"] and cbs[0]["note"] == "Rappeler après 15 h"
    bell = client.get("/api/notifications").json()["items"]
    assert any(n["key"].startswith("pfcb:") and "SAHEL NEGOCE" in n["title"] for n in bell)
    opp = {o["key"]: o for o in client.get("/api/portfolio/summary").json()["opportunities"]}
    assert (opp["pro-rc"]["called"], opp["pro-rc"]["interested"]) == (1, 1)
    # liste d'appels : jamais appelés d'abord
    calls = client.get("/api/portfolio/clients", params={"rule": "pro-rc", "calls_first": True}).json()["items"]
    assert calls[-1]["name"] == "SAHEL NEGOCE"
    assert client.get("/api/portfolio/clients", params={"rule": "pro-rc", "called": "never"}).json()["total"] == 2
    # un nouvel appel solde le rappel
    client.post(f"/api/portfolio/clients/{sahel['id']}/calls", json={"outcome": "done"}, headers=ORIGIN)
    assert client.get("/api/portfolio/callbacks").json()["items"] == []
    detail = client.get(f"/api/portfolio/clients/{sahel['id']}").json()
    assert len(detail["calls"]) == 3 and "RC entreprise" in detail["missing"]


def test_import_refused_for_wrong_file(db, tmp_path):
    p = tmp_path / "autre.csv"
    p.write_text("Nom;Email\nX;x@y.ma", encoding="utf-8")
    with get_session() as s:
        try:
            pf.import_file(s, p)
            raise AssertionError("aurait dû refuser")
        except pf.PortfolioError as exc:
            assert "POLICE" in str(exc) and "DIAMM" in str(exc)


def test_phone_parsing():
    assert pf.phones_of("0674904197- LEILA", "0522-66-01-52") == [{"number": "0674904197", "label": "Leila"},
                                                                    {"number": "0522-66-01-52", "label": ""}]
    assert pf.phones_of("0661000001", "0661000001 / bureau") == [{"number": "0661000001", "label": ""}]
    assert pf.phones_of("pas de numéro") == []
    assert pf.client_key("  Sté  Atlas-Béton ") == "STE ATLAS BETON" and pf.family_of("AUTO FLOTTE") == "Flotte auto"
    assert date.today() - timedelta(days=1) < date.today()

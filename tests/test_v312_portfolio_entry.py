"""V3.12 : saisie des nouveaux clients et contrats dans le Portefeuille (relais de DIAMM)."""
from tests.test_m4_engine import ORIGIN
from tests.test_v310_portfolio import _file, _import


def test_new_client_and_contract_then_reimport_keeps_them(client, db, tmp_path):
    _import(tmp_path)
    opts = client.get("/api/portfolio/options").json()
    assert "AXA ASSURANCE MAROC" in opts["insurers"]
    assert any(f["family"] == "Habitation" and "MULTIRISQUE HABITATIONS" in f["branches"] for f in opts["families"])
    r = client.post("/api/portfolio/clients", json={"name": "Hajji Kenza", "segment": "particulier",
                    "phones": [{"number": "0661 22 33 44", "label": "portable"}], "email": "kenza.hajji@exemple.ma",
                    "note": "Recommandée par Karim Bennani"}, headers=ORIGIN)
    assert r.status_code == 200, r.text
    c = r.json()
    assert c["source"] == "appli" and c["phones"] == [{"number": "0661223344", "label": "portable"}] and c["contact_id"]
    # doublon de nom refusé, avec le lien vers la fiche existante
    dup = client.post("/api/portfolio/clients", json={"name": "HAJJI  KENZA"}, headers=ORIGIN)
    assert dup.status_code == 409 and dup.json()["detail"]["existing_id"] == c["id"]
    # contrat
    d = client.post(f"/api/portfolio/clients/{c['id']}/contracts", json={"insurer": "Wafa Assurance", "policy": "W-2026-001",
                    "branch": "Multirisque habitations", "start_date": "2026-11-13", "due_date": "2027-11-12",
                    "premium": 1850}, headers=ORIGIN).json()
    ct = d["items"][0]
    assert (ct["insurer"], ct["family"], ct["source"], ct["premium"], ct["due_date"]) == (
        "WAFA ASSURANCE", "Habitation", "appli", 1850.0, "2027-11-12")
    assert d["contracts"] == 1 and "Habitation" in d["families"]
    # même police deux fois : refusé
    again = client.post(f"/api/portfolio/clients/{c['id']}/contracts", json={"insurer": "WAFA ASSURANCE", "policy": "W-2026-001",
                        "branch": "AUTO PARTICULIERS"}, headers=ORIGIN)
    assert again.status_code == 422
    # branche obligatoire
    assert client.post(f"/api/portfolio/clients/{c['id']}/contracts", json={"insurer": "AXA", "policy": "X1"},
                       headers=ORIGIN).status_code == 422
    # résilier puis réactiver
    d = client.put(f"/api/portfolio/contracts/{ct['id']}", json={"cancelled": True, "cancelled_on": "2026-12-31"}, headers=ORIGIN).json()
    assert d["items"][0]["cancelled"] and d["contracts"] == 0
    d = client.put(f"/api/portfolio/contracts/{ct['id']}", json={"cancelled": False}, headers=ORIGIN).json()
    assert not d["items"][0]["cancelled"] and d["contracts"] == 1
    # le tableau de bord le compte
    s = client.get("/api/portfolio/summary").json()
    assert s["clients"] == 6 and s["premium_total"] == 1850.0
    # réimport DIAMM : rien de ce qui a été saisi n'est perdu
    _import(tmp_path)
    d = client.get(f"/api/portfolio/clients/{c['id']}").json()
    assert d["contracts"] == 1 and d["email"] == "kenza.hajji@exemple.ma" and d["note"] == "Recommandée par Karim Bennani"


def test_edit_client_and_delete_only_manual_contracts(client, db, tmp_path):
    _import(tmp_path)
    rows = client.get("/api/portfolio/clients", params={"q": "SAHEL"}).json()["items"]
    sahel = rows[0]
    d = client.put(f"/api/portfolio/clients/{sahel['id']}", json={"name": "Sahel Négoce SARL", "segment": "pro",
                   "phones": [{"number": "0522 00 00 99", "label": "standard"}]}, headers=ORIGIN).json()
    assert d["name"] == "Sahel Négoce SARL" and d["phones"][0]["label"] == "standard"
    diamm = d["items"][0]
    assert client.delete(f"/api/portfolio/contracts/{diamm['id']}", headers=ORIGIN).status_code == 422  # venu de DIAMM
    d = client.post(f"/api/portfolio/clients/{sahel['id']}/contracts", json={"insurer": "SANAD", "policy": "S-1",
                    "branch": "RC. EXPLOITATION"}, headers=ORIGIN).json()
    mine = next(x for x in d["items"] if x["policy"] == "S-1")
    assert mine["family"] == "RC entreprise"
    d = client.delete(f"/api/portfolio/contracts/{mine['id']}", headers=ORIGIN).json()
    assert all(x["policy"] != "S-1" for x in d["items"])
    # renommer en un nom déjà pris : refusé
    other = client.get("/api/portfolio/clients", params={"q": "TAZI"}).json()["items"][0]
    assert client.put(f"/api/portfolio/clients/{other['id']}", json={"name": "Sahel Negoce SARL"}, headers=ORIGIN).status_code == 409
    assert _file  # (fixture de fichier partagée avec test_v310)

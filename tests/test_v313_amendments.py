"""V3.13 : avenants rattachés aux contrats, et pièces jointes (contrat scanné, avenant scanné)."""
from tests.test_m4_engine import ORIGIN
from tests.test_v310_portfolio import _import


def _upload(client, name="contrat.pdf", data=b"%PDF-1.4 contrat scanne"):
    r = client.post("/api/attachments", files={"file": (name, data, "application/pdf")}, headers=ORIGIN)
    assert r.status_code == 200, r.text
    return r.json()


def _setup(client, tmp_path):
    _import(tmp_path)
    c = client.post("/api/portfolio/clients", json={"name": "Flotte Demo SARL", "segment": "pro"}, headers=ORIGIN).json()
    scan = _upload(client)
    d = client.post(f"/api/portfolio/clients/{c['id']}/contracts", json={
        "insurer": "AXA ASSURANCE MAROC", "policy": "FL-2026-9", "branch": "AUTO FLOTTE", "start_date": "2026-11-01",
        "premium": 42000, "fleet": True, "attachment_ids": [scan["id"]]}, headers=ORIGIN).json()
    return c, d["items"][0], scan


def test_contract_keeps_its_scan(client, db, tmp_path):
    c, ct, scan = _setup(client, tmp_path)
    assert [f["name"] for f in ct["files"]] == ["contrat.pdf"] and ct["files"][0]["token"] == scan["token"]
    dl = client.get(f"/api/attachments/{scan['id']}", params={"t": scan["token"]})
    assert dl.status_code == 200 and dl.content.startswith(b"%PDF")
    cg = _upload(client, "conditions-generales.pdf", b"%PDF cg")
    d = client.put(f"/api/portfolio/contracts/{ct['id']}", json={"attachment_ids": [scan["id"], cg["id"]]}, headers=ORIGIN).json()
    assert [f["name"] for f in d["items"][0]["files"]] == ["contrat.pdf", "conditions-generales.pdf"]
    assert client.put(f"/api/portfolio/contracts/{ct['id']}", json={"attachment_ids": [999999]}, headers=ORIGIN).status_code == 422


def test_amendments_attach_to_the_contract(client, db, tmp_path):
    c, ct, _ = _setup(client, tmp_path)
    kinds = client.get("/api/portfolio/amendment-kinds").json()["items"]
    assert kinds[0] == "Renouvellement" and "Ajout de véhicule (flotte)" in kinds
    av_scan = _upload(client, "avenant-1.pdf", b"%PDF avenant")
    d = client.post(f"/api/portfolio/contracts/{ct['id']}/amendments", json={
        "effective_on": "2026-12-01", "kind": "Ajout de véhicule (flotte)", "number": "AV-1",
        "description": "Ajout du camion 12345-A-6", "premium_delta": 3500, "attachment_ids": [av_scan["id"]]}, headers=ORIGIN).json()
    d = client.post(f"/api/portfolio/contracts/{ct['id']}/amendments", json={
        "effective_on": "2027-01-15", "kind": "Retrait de véhicule", "premium_delta": -1200.5}, headers=ORIGIN).json()
    item = d["items"][0]
    assert [a["number"] for a in item["amendments"]] == ["", "AV-1"]          # le plus récent d'abord
    assert item["amendments"][1]["files"][0]["name"] == "avenant-1.pdf"
    assert item["amendments_premium"] == 2299.5
    first = item["amendments"][1]["id"]
    d = client.put(f"/api/portfolio/amendments/{first}", json={"description": "Ajout du camion 12345-A-6 (benne)"}, headers=ORIGIN).json()
    assert d["items"][0]["amendments"][1]["description"].endswith("(benne)")
    # date d'effet obligatoire, objet obligatoire
    assert client.post(f"/api/portfolio/contracts/{ct['id']}/amendments", json={"kind": "Autre"}, headers=ORIGIN).status_code == 422
    assert client.post(f"/api/portfolio/contracts/{ct['id']}/amendments", json={"effective_on": "2027-02-01"}, headers=ORIGIN).status_code == 422
    d = client.delete(f"/api/portfolio/amendments/{first}", headers=ORIGIN).json()
    assert len(d["items"][0]["amendments"]) == 1
    # supprimer le contrat (saisi dans l'appli) emporte ses avenants
    d = client.delete(f"/api/portfolio/contracts/{ct['id']}", headers=ORIGIN).json()
    assert d["items"] == []


def test_amendment_on_a_diamm_contract(client, db, tmp_path):
    _import(tmp_path)
    rows = client.get("/api/portfolio/clients", params={"q": "ATLAS BETON"}).json()["items"]
    det = client.get(f"/api/portfolio/clients/{rows[0]['id']}").json()
    ct = next(x for x in det["items"] if not x["cancelled"])
    d = client.post(f"/api/portfolio/contracts/{ct['id']}/amendments", json={"effective_on": "2026-11-20",
                    "kind": "Changement de garanties", "description": "Ajout bris de glace"}, headers=ORIGIN).json()
    assert any(a["kind"] == "Changement de garanties" for x in d["items"] for a in x["amendments"])
    # un nouvel import DIAMM (mise à jour du portefeuille) ne fait perdre ni l'avenant ni le scan
    scan = _upload(client, "police-diamm.pdf", b"%PDF scan")
    client.put(f"/api/portfolio/contracts/{ct['id']}", json={"attachment_ids": [scan["id"]]}, headers=ORIGIN)
    _import(tmp_path)
    again = next(x for x in client.get(f"/api/portfolio/clients/{rows[0]['id']}").json()["items"] if x["id"] == ct["id"])
    assert [f["name"] for f in again["files"]] == ["police-diamm.pdf"]
    assert [a["description"] for a in again["amendments"]] == ["Ajout bris de glace"]


def test_full_policy_sheet(client, db, tmp_path):
    """Fiche police : souscription, n° apériteur, co-assurance, dernier sinistre ; un import ne les efface pas."""
    _import(tmp_path)
    rows = client.get("/api/portfolio/clients", params={"q": "ATLAS BETON"}).json()["items"]
    det = client.get(f"/api/portfolio/clients/{rows[0]['id']}").json()
    ct = next(x for x in det["items"] if not x["cancelled"])
    assert ct["coinsurance"] is False and ct["aperiteur_no"] == "" and ct["subscribed_on"] is None
    d = client.put(f"/api/portfolio/contracts/{ct['id']}", json={
        "subscribed_on": "2024-03-01", "start_date": "2024-04-01", "due_date": "2027-03-31", "aperiteur_no": "AP-778",
        "coinsurance": True, "last_claim_on": "2026-06-12"}, headers=ORIGIN).json()
    got = next(x for x in d["items"] if x["id"] == ct["id"])
    assert (got["subscribed_on"], got["start_date"], got["due_date"], got["aperiteur_no"], got["coinsurance"], got["last_claim_on"]) == \
        ("2024-03-01", "2024-04-01", "2027-03-31", "AP-778", True, "2026-06-12")
    _import(tmp_path)  # l'export DIAMM actuel n'a pas ces colonnes : rien n'est effacé
    again = next(x for x in client.get(f"/api/portfolio/clients/{rows[0]['id']}").json()["items"] if x["id"] == ct["id"])
    assert (again["subscribed_on"], again["aperiteur_no"], again["coinsurance"], again["last_claim_on"], again["due_date"]) == \
        ("2024-03-01", "AP-778", True, "2026-06-12", "2027-03-31")


def test_import_reads_policy_dates_when_present(client, db, tmp_path):
    from pathlib import Path

    from app import portfolio as pf
    from app.db import get_session
    p = Path(tmp_path) / "export.csv"
    p.write_text("CLIENT;Particulier;POLICE;COMPAGNIE;BRANCHE;DATE EFFET;DATE SOUSCRIPTION;ECHEANCE;N APERITEUR;CO-ASSURANCE;DATE DERNIER SINISTRE\n"
                 "STE DEMO COASS SARL;N;P-1;AXA ASSURANCE MAROC;MULTIRISQUE INDUSTRIELLE;01/01/2026;15/12/2025;31/12/2026;AX-55;O;03/05/2026\n"
                 "STE DEMO COASS SARL;N;P-2;AXA ASSURANCE MAROC;RC. EXPLOITATION;;;;;;\n", encoding="utf-8")
    with get_session() as s:
        pf.import_file(s, p)
        s.commit()
    rows = client.get("/api/portfolio/clients", params={"q": "DEMO COASS"}).json()["items"]
    items = {x["policy"]: x for x in client.get(f"/api/portfolio/clients/{rows[0]['id']}").json()["items"]}
    a = items["P-1"]
    assert (a["start_date"], a["subscribed_on"], a["due_date"], a["aperiteur_no"], a["coinsurance"], a["last_claim_on"]) == \
        ("2026-01-01", "2025-12-15", "2026-12-31", "AX-55", True, "2026-05-03")
    assert items["P-2"]["coinsurance"] is False and items["P-2"]["start_date"] is None

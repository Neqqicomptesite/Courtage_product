"""Contrats et échéances : saisie, rappels de préavis (2 semaines puis 1 semaine avant la date
limite), dossier gagné → contrat, renouvellement (même compagnie, autre compagnie, perdu),
tacite reconduction, listes et totaux du portefeuille."""
from datetime import date, timedelta

from sqlalchemy import select

from app import contracts
from app.db import get_session
from app.models import Contract, Reminder
from tests.test_quotes import O, _rows, _setup


def _reminders(cid: int) -> list[date]:
    with get_session() as s:
        return sorted(r.due_on for r in s.scalars(select(Reminder).where(Reminder.contract_id == cid,
                                                                          Reminder.done_at.is_(None))))


def test_contract_reminders_follow_the_notice_deadline(client):
    client_co, ins1, _ = _setup()
    today = contracts.today()
    end = today + timedelta(days=120)
    r = client.post("/api/contracts", json={"company_id": client_co, "insurer_id": ins1, "branch": "Flotte",
                                            "policy_number": "FL-2026-001", "premium": "185 000",
                                            "commission_rate": "12,5", "end_date": end.isoformat()}, headers=O)
    assert r.status_code == 200, r.text
    c = r.json()
    assert c["client_name"] == "Atlas Logistique" and c["insurer_name"] == "Assurance Alpha"
    assert c["notice_days"] == 60 and c["deadline"] == (end - timedelta(days=60)).isoformat()
    assert c["commission"] == 23125 and c["status"] == "active" and c["urgency"] == "soon"
    dl = end - timedelta(days=60)
    assert _reminders(c["id"]) == [dl - timedelta(days=14), dl - timedelta(days=7)]
    # préavis saisi autrement : rappels recalculés
    c = client.patch(f"/api/contracts/{c['id']}", json={"notice_days": "90"}, headers=O).json()
    dl = end - timedelta(days=90)
    assert _reminders(c["id"]) == [dl - timedelta(days=14), dl - timedelta(days=7)]
    # date limite dans 10 jours : un rappel aujourd'hui, puis 1 semaine avant
    c = client.patch(f"/api/contracts/{c['id']}", json={"end_date": (today + timedelta(days=100)).isoformat()},
                     headers=O).json()
    assert _reminders(c["id"]) == [today, today + timedelta(days=3)] and c["urgency"] == "urgent"
    # préavis dépassé : plus de rappel
    c = client.patch(f"/api/contracts/{c['id']}", json={"end_date": (today + timedelta(days=30)).isoformat()},
                     headers=O).json()
    assert _reminders(c["id"]) == [] and c["urgency"] == "past_notice"
    # le rappel ouvre le contrat depuis la cloche
    client.patch(f"/api/contracts/{c['id']}", json={"end_date": (today + timedelta(days=95)).isoformat()}, headers=O)  # préavis 90 j : limite dans 5 jours
    notes = client.get("/api/notifications").json()["items"]
    assert any(n["href"] == f"/contracts/{c['id']}" for n in notes), (notes, _reminders(c["id"]))
    # champs obligatoires
    bad = client.post("/api/contracts", json={"branch": "Flotte"}, headers=O)
    assert bad.status_code == 422 and {"client_name", "end_date", "insurer_id"} <= set(bad.json()["detail"]["errors"])
    # date d'effet seule : échéance = un an moins un jour
    c2 = client.post("/api/contracts", json={"client_name": "Particulier", "insurer_name": "Compagnie hors base",
                                             "branch": "Santé", "start_date": "2026-03-01"}, headers=O).json()
    assert c2["end_date"] == "2027-02-28"


def test_won_case_becomes_contract_and_renewal_cycle(client):
    client_co, ins1, ins2 = _setup()
    case = client.post("/api/quotes", json={"branch": "Flotte", "company_id": client_co,
                                            "fields": {"activite": "Transport", "nb_vehicules": "12",
                                                       "date_effet": "2027-01-01", "preavis_jours": "45"}},
                       headers=O).json()
    case = client.post(f"/api/quotes/{case['id']}/insurers", json={"company_ids": [ins1, ins2]}, headers=O).json()
    a, b = _rows(case, "Assurance Alpha")[0], _rows(case, "Beta Assurances")[0]
    client.patch(f"/api/quotes/{case['id']}/insurers/{a['id']}", json={"status": "offer", "offer_premium": "190000"}, headers=O)
    client.patch(f"/api/quotes/{case['id']}/insurers/{b['id']}", json={"status": "offer", "offer_premium": "176 000",
                                                                       "offer_rate": "3 %"}, headers=O)
    draft = client.get(f"/api/quotes/{case['id']}/contract-draft").json()
    it = draft["items"][0]
    assert draft["renewal_of"] is None and len(it["choices"]) == 2
    assert it["insurer_id"] == ins2 and it["premium"] == 176000 and it["rate"] == "3 %"   # la moins chère
    assert it["start_date"] == "2027-01-01" and it["end_date"] == "2027-12-31" and it["notice_days"] == 45
    res = client.post(f"/api/quotes/{case['id']}/win", json={"items": [{**it, "policy_number": "B-778"}]}, headers=O).json()
    assert res["quote"]["stage"] == "won"
    c = res["contracts"][0]
    assert c["insurer_name"] == "Beta Assurances" and c["notice_days"] == 45 and c["quote_case"]["id"] == case["id"]
    assert c["deadline"] == "2027-11-16" and len(_reminders(c["id"])) == 2

    # renouvellement : dossier pré-rempli, compagnie actuelle déjà consultée
    r = client.post(f"/api/contracts/{c['id']}/start-renewal", headers=O).json()
    assert r["contract"]["status"] == "renewing" and r["contract"]["renewal_case"]["id"] == r["quote_id"]
    assert client.post(f"/api/contracts/{c['id']}/start-renewal", headers=O).status_code == 422  # déjà ouvert
    ren = client.get(f"/api/quotes/{r['quote_id']}").json()
    assert ren["branches"] == ["Flotte"] and ren["current_insurer"] == "Beta Assurances" and ren["current_premium"] == 176000
    assert ren["fields"]["date_effet"] == "2028-01-01" and [x["company"] for x in ren["companies"]] == ["Beta Assurances"]
    row = _rows(ren, "Beta Assurances")[0]
    client.patch(f"/api/quotes/{ren['id']}/insurers/{row['id']}", json={"status": "offer", "offer_premium": "181000"}, headers=O)
    d2 = client.get(f"/api/quotes/{ren['id']}/contract-draft").json()
    assert d2["renewal_of"]["id"] == c["id"] and d2["items"][0]["policy_number"] == "B-778"
    assert d2["items"][0]["start_date"] == "2028-01-01"
    res = client.post(f"/api/quotes/{ren['id']}/win", json={"items": d2["items"]}, headers=O).json()
    same = res["contracts"][0]
    assert same["id"] == c["id"] and same["status"] == "active" and same["premium"] == 181000
    assert same["end_date"] == "2028-12-31" and same["renewal_case"] is None
    assert "Renouvelé" in same["history"][0]["text"] and "176 000" in same["history"][0]["text"]

    # renouvellement suivant : une autre compagnie est retenue → l'ancien contrat est remplacé
    r = client.post(f"/api/contracts/{c['id']}/start-renewal", headers=O).json()
    ren = client.post(f"/api/quotes/{r['quote_id']}/insurers", json={"company_ids": [ins1]}, headers=O).json()
    d3 = client.get(f"/api/quotes/{ren['id']}/contract-draft").json()
    item = {**d3["items"][0], "insurer_id": ins1, "premium": 170000, "policy_number": "A-1"}
    new = client.post(f"/api/quotes/{ren['id']}/win", json={"items": [item]}, headers=O).json()["contracts"][0]
    old = client.get(f"/api/contracts/{c['id']}").json()
    assert new["id"] != c["id"] and new["previous_id"] == c["id"] and new["insurer_name"] == "Assurance Alpha"
    assert old["status"] == "ended" and old["end_reason"].startswith("Remplacé : Assurance Alpha")
    assert _reminders(c["id"]) == []

    # renouvellement perdu → le contrat se termine
    r = client.post(f"/api/contracts/{new['id']}/start-renewal", headers=O).json()
    client.patch(f"/api/quotes/{r['quote_id']}", json={"stage": "lost", "lost_reason": "Parti chez un concurrent"}, headers=O)
    lost = client.get(f"/api/contracts/{new['id']}").json()
    assert lost["status"] == "ended" and "Parti chez un concurrent" in lost["end_reason"]

    # gagné sans contrat : possible
    other = client.post("/api/quotes", json={"branch": "Santé", "company_id": client_co}, headers=O).json()
    res = client.post(f"/api/quotes/{other['id']}/win", json={"items": []}, headers=O).json()
    assert res["quote"]["stage"] == "won" and res["contracts"] == []


def test_renew_same_tacit_roll_and_portfolio(client):
    client_co, ins1, ins2 = _setup()
    today = contracts.today()
    mk = lambda **kw: client.post("/api/contracts", json={"company_id": client_co, "insurer_id": ins1, "branch": "Flotte",  # noqa: E731
                                                         "premium": 100000, "commission_rate": 10, **kw}, headers=O).json()
    soon = mk(end_date=(today + timedelta(days=70)).isoformat())                     # préavis dans 10 jours
    later = mk(end_date=(today + timedelta(days=300)).isoformat(), insurer_id=ins2)
    past = mk(end_date=(today - timedelta(days=3)).isoformat(), start_date=(today - timedelta(days=368)).isoformat())
    fixed = mk(end_date=(today - timedelta(days=3)).isoformat(), tacit=False)
    with get_session() as s:
        assert contracts.roll_tacit(s) == 1
        s.commit()
        p, f = s.get(Contract, past["id"]), s.get(Contract, fixed["id"])
        assert p.end_date == contracts.add_year(today - timedelta(days=3)) and p.status == "active"
        assert "Reconduit tacitement" in p.history[-1]["text"] and f.end_date == today - timedelta(days=3)
    assert client.get(f"/api/contracts/{fixed['id']}").json()["urgency"] == "expired"
    # renouvelé à l'identique, prime revue
    r = client.post(f"/api/contracts/{soon['id']}/renew", json={"premium": "108 000"}, headers=O).json()
    assert r["premium"] == 108000 and r["end_date"] == contracts.default_end(today + timedelta(days=71)).isoformat()
    # listes et totaux
    assert client.get("/api/contracts").json()["filter"] == "active"   # par défaut : tout le portefeuille
    data = client.get("/api/contracts?f=upcoming").json()
    assert data["filter"] == "upcoming" and [i["id"] for i in data["items"]] == [fixed["id"]]   # échu sans reconduction
    all_ = client.get("/api/contracts?f=active").json()
    assert {i["id"] for i in all_["items"]} == {soon["id"], later["id"], past["id"], fixed["id"]}
    sm = all_["summary"]
    assert sm["active"] == 4 and sm["premium"] == 408000 and sm["commission"] == 40800
    assert client.get("/api/contracts?f=active&q=Beta").json()["items"][0]["id"] == later["id"]
    client.post(f"/api/contracts/{later['id']}/end", json={"reason": "Résilié par le client"}, headers=O)
    assert [i["id"] for i in client.get("/api/contracts?f=ended").json()["items"]] == [later["id"]]
    assert client.post(f"/api/contracts/{soon['id']}/end", json={"reason": " "}, headers=O).status_code == 422
    assert client.delete(f"/api/contracts/{fixed['id']}", headers=O).json() == {"ok": True}
    assert _reminders(fixed["id"]) == []


def test_amounts_branch_settings_search_and_export(client):
    """Base de calcul × taux = prime nette ; taxes et commission par défaut selon la branche
    (réglables) ; recherche par police, compagnie, client, échéance ; export Excel."""
    from io import BytesIO

    from openpyxl import load_workbook
    client_co, ins1, ins2 = _setup()
    cfg = client.get("/api/contracts/branches").json()
    assert cfg["confirmed"] is False
    at, rc = cfg["items"]["Accidents du travail"], cfg["items"]["RC professionnelle"]
    assert at["base_label"] == "Masse salariale" and at["tax_rate"] == 0 and rc["base_label"] == "Chiffre d'affaires"
    assert rc["tax_rate"] == 14 and rc["parafiscal_rate"] == 1
    items = cfg["items"]
    items["RC professionnelle"] = {**rc, "commission_rate": "15"}
    items["Accidents du travail"] = {**at, "commission_rate": 10}
    saved = client.put("/api/contracts/branches", json={"items": items}, headers=O).json()
    assert saved["confirmed"] is True and saved["items"]["RC professionnelle"]["commission_rate"] == 15
    # RC pro : CA 2 000 000 × 0,35 % = 7 000 de prime nette ; taxes 14 % + 1 % sur prime + accessoires
    c = client.post("/api/contracts", json={"company_id": client_co, "insurer_id": ins1, "branch": "RC professionnelle",
                                            "policy_number": "RC 2026 / 0042", "base_amount": "2 000 000", "rate": "0,35 %",
                                            "accessories": 200, "end_date": "2027-06-30"}, headers=O).json()
    assert c["base_label"] == "Chiffre d'affaires" and c["premium"] == 7000 and c["commission_rate"] == 15
    assert c["tax"] == 1008 and c["parafiscal"] == 72 and c["taxes"] == 1080 and c["ttc"] == 8280 and c["commission"] == 1050
    # taux en pour mille, et prime saisie à la main (minimum de prime) : la saisie l'emporte
    c = client.patch(f"/api/contracts/{c['id']}", json={"rate": "4 ‰"}, headers=O).json()
    assert c["premium"] == 8000
    c = client.patch(f"/api/contracts/{c['id']}", json={"rate": "3 ‰", "premium": "9500"}, headers=O).json()
    assert c["premium"] == 9500
    # AT : exonéré, commission de la branche ; changer de branche reprend ses taux
    at_c = client.post("/api/contracts", json={"client_name": "Textile Démo", "insurer_id": ins2, "branch": "Accidents du travail",
                                               "policy_number": "AT-77", "base_amount": 3000000, "rate": "2,5 %",
                                               "end_date": "2027-01-31"}, headers=O).json()
    assert at_c["premium"] == 75000 and at_c["taxes"] == 0 and at_c["ttc"] == 75000 and at_c["commission"] == 7500
    moved = client.patch(f"/api/contracts/{at_c['id']}", json={"branch": "RC professionnelle"}, headers=O).json()
    assert moved["tax_rate"] == 14 and moved["commission_rate"] == 15
    client.patch(f"/api/contracts/{at_c['id']}", json={"branch": "Accidents du travail"}, headers=O)
    # recherche
    get = lambda **p: [i["id"] for i in client.get("/api/contracts", params={"f": "all", **p}).json()["items"]]  # noqa: E731
    assert get(policy="2026/0042") == [c["id"]] and get(policy="at-77") == [at_c["id"]]
    assert get(insurer=str(ins2)) == [at_c["id"]] and get(company_id=client_co) == [c["id"]]
    assert get(q="textile accidents") == [at_c["id"]] and get(q="Atlas Alpha") == [c["id"]]
    assert get(end_from="2027-03-01") == [c["id"]] and get(end_to="2027-02-01") == [at_c["id"]]
    assert get(sort="premium") == [at_c["id"], c["id"]]
    r = client.get("/api/contracts", params={"f": "all"}).json()
    assert r["totals"] == {"count": 2, "premium": 84500, "ttc": 75000 + 9700 + 1455, "commission": 7500 + 1425}
    # export Excel : mêmes filtres
    x = client.get("/api/contracts/export.xlsx", params={"f": "all", "branch": "Accidents du travail"})
    assert x.status_code == 200 and "spreadsheetml" in x.headers["content-type"]
    ws = load_workbook(BytesIO(x.content)).active
    assert ws.max_row == 2 and ws["A2"].value == "Textile Démo" and ws["H2"].value == 75000 and ws["E2"].value == "Masse salariale"

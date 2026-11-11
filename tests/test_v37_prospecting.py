"""V3.7 : recherche de prospects via looot, avec un faux serveur looot (aucun appel réel, rien de payé)."""
import json

import httpx
import pytest
from sqlalchemy import select

from app import prospecting as pr
from app.db import get_session
from app.models import Contact, ContactListMember, ProspectSearch, Suppression
from tests.test_m4_engine import ORIGIN, world  # noqa: F401
from tests.test_v3_auth import server  # noqa: F401

PROSPEO_INDUSTRIES = set((__import__("pathlib").Path(__file__).parent / "prospeo_industries.txt").read_text(encoding="utf-8").splitlines())


def _person(i, findable=True, industry="Construction", domain=None):
    return {"person": {"person_id": f"p{i}", "first_name": f"Prénom{i}", "last_name": f"Nom{i}",
                       "current_job_title": "Directeur général", "linkedin_url": f"https://www.linkedin.com/in/p{i}",
                       "location": {"city": "Casablanca", "country": "Morocco"},
                       "email": {"status": "VERIFIED" if findable else "UNAVAILABLE"}},
            "company": {"name": f"Société {i}", "domain": domain or f"societe{i}.demo.test", "industry": industry,
                        "employee_range": "51-100", "website": f"https://societe{i}.demo.test"}}


class FakeLooot:
    def __init__(self, pages=2, per_page=4, balance=2.5, no_credit_after=None):
        self.calls, self.keys, self.balance = [], set(), balance
        self.pages, self.per_page, self.no_credit_after = pages, per_page, no_credit_after

    def __call__(self, request: httpx.Request) -> httpx.Response:
        if request.headers.get("authorization") != "Bearer cle-test-1234567890":
            return httpx.Response(401, json={"error": {"code": "unauthorized", "message": "bad key"}})
        if request.url.path == "/v1/balance":
            return httpx.Response(200, json={"available": self.balance})
        body = json.loads(request.content)
        self.calls.append(body)
        if self.no_credit_after is not None and len(self.calls) > self.no_credit_after:
            return httpx.Response(402, json={"error": {"code": "insufficient_balance", "message": "no credit"}})
        self.keys.add(body["idempotencyKey"])
        if body["endpointId"] == pr.SEARCH_ENDPOINT:
            page = body["input"]["page"]
            start = (page - 1) * self.per_page
            people = [_person(start + i, findable=(start + i) % 4 != 3) for i in range(self.per_page)] if page <= self.pages else []
            return httpx.Response(200, json={"status": "completed", "outcome": "miss", "actualCost": 0.039,
                                             "result": {"results": people, "pagination": {
                                                 "total_count": self.pages * self.per_page, "total_page": self.pages}}})
        inp = body["input"]
        if inp["last_name"].endswith("2"):  # pas d'email pour ceux-là
            return httpx.Response(200, json={"status": "completed", "outcome": "miss", "actualCost": 0})
        email = f"p{inp['last_name'][3:]}@{inp['domain']}"
        return httpx.Response(200, json={"status": "completed", "outcome": "hit", "actualCost": 0.005,
                                         "normalized": {"fields": {"email": email, "check": "valid"}}})


@pytest.fixture
def looot(monkeypatch):
    fake = FakeLooot()
    monkeypatch.setattr(pr, "_TRANSPORT", httpx.MockTransport(fake))
    return fake


def test_filters_follow_the_form():
    c = pr.clean_criteria({"functions": ["FIN", "XX"], "sectors": ["BTP"], "cities": ["Tanger", "Paris"], "sizes": ["pme"], "wanted": 9999})
    assert c == {"functions": ["FIN"], "sectors": ["BTP"], "details": [], "cities": ["Tanger"], "sizes": ["pme"], "wanted": pr.MAX_WANTED}
    f = pr.filters(c)
    assert "Directeur financier" in f["person_job_title"]["include"] and "CFO" in f["person_job_title"]["include"]
    assert f["person_location_search"] == {"include": ["Tangier, Morocco"]}
    assert "Construction" in f["company_industry"]["include"] and "Real Estate" in f["company_industry"]["include"] and f["company_headcount_range"] == ["51-100", "101-200"]
    assert pr.filters(pr.clean_criteria({"functions": ["DIR"]}))["person_location_search"] == {"include": ["Morocco"]}
    with pytest.raises(ValueError):
        pr.clean_criteria({"functions": []})
    # précisions : banque seulement dans les services, tout le BTP, une précision inconnue ignorée
    c = pr.clean_criteria({"functions": ["DIR"], "sectors": ["BTP"], "details": ["SRV.banque", "SRV.xx"]})
    assert c["sectors"] == ["BTP", "SRV"] and c["details"] == ["SRV.banque"]
    inds = pr.filters(c)["company_industry"]["include"]
    assert "Banking" in inds and "Construction" in inds and "Insurance" not in inds
    assert "Banque, finance & crédit" in pr.describe(c)


def test_every_industry_is_a_valid_prospeo_value():
    """Liste relevée sur prospeo.io/api-docs/enum/industries : une valeur inventée ferait échouer la recherche."""
    for code, s in pr.SECTORS.items():
        for lbl, inds in s["details"].values():
            for i in inds:
                assert i in PROSPEO_INDUSTRIES, (code, lbl, i)


def test_key_is_checked_then_stored(client, world, looot):  # noqa: F811
    assert client.get("/api/prospecting", headers=ORIGIN).json()["configured"] is False
    assert client.put("/api/prospecting/key", json={"key": "mauvaise-cle-123456"}, headers=ORIGIN).status_code == 422
    r = client.put("/api/prospecting/key", json={"key": "cle-test-1234567890"}, headers=ORIGIN).json()
    assert r == {"configured": True, "balance": 2.5}
    assert client.get("/api/prospecting/balance", headers=ORIGIN).json() == {"balance": 2.5}
    assert "cle-test" not in json.dumps(client.get("/api/prospecting", headers=ORIGIN).json())  # jamais réaffichée


def test_preview_then_background_search_imports_into_a_list(client, world, looot):  # noqa: F811
    pr.set_key("cle-test-1234567890")
    with get_session() as s:  # déjà connu : Prénom1 Nom1 chez societe1 ; exclu : prenom5@
        s.add(Contact(email="direction@societe1.demo.test", first_name="Prénom1", last_name="Nom1"))
        s.add(Suppression(email_or_domain="p5@societe5.demo.test", reason="test"))
        s.commit()
    prev = client.post("/api/prospecting/preview", json={"functions": ["DIR"], "sectors": ["BTP"], "wanted": 3},
                       headers=ORIGIN).json()
    assert prev["status"] == "preview" and prev["total_found"] == 8 and len(prev["sample"]) == 4
    assert prev["estimate"]["findable_ratio"] == 0.75 and prev["cost_usd"] == 0.039
    sid = prev["id"]
    assert client.post(f"/api/prospecting/{sid}/start", json={"wanted": 3}, headers=ORIGIN).json()["status"] == "running"
    for _ in range(6):
        pr.tick()
    d = client.get(f"/api/prospecting/{sid}", headers=ORIGIN).json()
    assert d["status"] == "done" and d["imported"] == 3, json.dumps(d)
    assert d["skipped_existing"] >= 1 and d["skipped_no_email"] >= 1
    with get_session() as s:
        ps = s.get(ProspectSearch, sid)
        made = s.scalars(select(Contact).where(Contact.source.like("Recherche looot%"))).all()
        assert len(made) == 3 and all(c.sequence_code == "DIR-BTP" and c.kind == "prospect" for c in made)
        assert all(c.custom.get("ville") == "Casablanca" and c.linkedin_url for c in made)
        assert s.scalar(select(ContactListMember.id).where(ContactListMember.list_id == ps.list_id)) is not None
    # page 1 jamais repayée ; chaque appel a sa clé d'idempotence
    pages = [c for c in looot.calls if c["endpointId"] == pr.SEARCH_ENDPOINT]
    assert [c["input"]["page"] for c in pages] == [1, 2] and len(looot.keys) == len(looot.calls)
    assert client.get("/api/prospecting", headers=ORIGIN).json()["items"][0]["id"] == sid


def test_stops_when_credit_runs_out(client, world, monkeypatch):  # noqa: F811
    fake = FakeLooot(no_credit_after=2)
    monkeypatch.setattr(pr, "_TRANSPORT", httpx.MockTransport(fake))
    pr.set_key("cle-test-1234567890")
    sid = client.post("/api/prospecting/preview", json={"functions": ["FIN"], "wanted": 50}, headers=ORIGIN).json()["id"]
    client.post(f"/api/prospecting/{sid}/start", json={}, headers=ORIGIN)
    pr.tick()
    d = client.get(f"/api/prospecting/{sid}", headers=ORIGIN).json()
    assert d["status"] == "stopped" and "Crédit looot épuisé" in d["error"] and d["imported"] >= 1


def test_stop_and_no_key(client, world, looot):  # noqa: F811
    assert client.post("/api/prospecting/preview", json={"functions": ["RH"]}, headers=ORIGIN).status_code == 409
    pr.set_key("cle-test-1234567890")
    sid = client.post("/api/prospecting/preview", json={"functions": ["RH"]}, headers=ORIGIN).json()["id"]
    client.post(f"/api/prospecting/{sid}/start", json={}, headers=ORIGIN)
    assert client.post(f"/api/prospecting/{sid}/stop", headers=ORIGIN).json()["status"] == "stopped"
    assert client.post(f"/api/prospecting/{sid}/start", json={}, headers=ORIGIN).status_code == 409


def test_reserved_to_admin(server):  # noqa: F811
    from tests.test_v3_auth import H
    assert server.get("/api/prospecting", headers=H("hamza@oddo.ma")).status_code == 403
    assert server.post("/api/prospecting/preview", json={"functions": ["DIR"]}, headers=H("hamza@oddo.ma")).status_code == 403
    assert server.get("/api/prospecting", headers=H("omar@oddo.ma")).status_code == 200

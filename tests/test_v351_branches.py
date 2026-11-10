"""V3.5.1 : branches Automobile (1 véhicule), Multirisque bureau, RC décennale, Assurance crédit.
Chaque champ de la fiche remplit son [champ] dans la demande aux compagnies ; renommer un dossier."""
import pytest

from app import quotes
from tests.test_m4_engine import world  # noqa: F401
from tests.test_quotes import O, _rows, _setup

NEW = ["Automobile", "Multirisque bureau", "RC décennale", "Assurance crédit"]


def _value(f):
    if f.get("options"):
        return f["options"][0]
    return {"number": "1200000", "date": "2027-01-15"}.get(f.get("type"), "Valeur test")


@pytest.mark.parametrize("branch", NEW)
def test_new_branch_request_is_complete(client, world, branch):  # noqa: F811
    client_co, ins1, _ = _setup()
    fields = {f["key"]: _value(f) for f in quotes.branch_def(branch)["fields"]}
    assert quotes.branch_def(branch)["docs"], "documents à demander au client"
    r = client.post("/api/quotes", json={"branch": branch, "company_id": client_co, "fields": fields}, headers=O)
    assert r.status_code == 200, r.text
    case = r.json()
    assert case["missing_labels"] == []
    case = client.post(f"/api/quotes/{case['id']}/insurers", json={"company_ids": [ins1]}, headers=O).json()
    row = _rows(case, "Assurance Alpha")[0]
    d = client.post(f"/api/quotes/{case['id']}/draft", json={"insurer_ids": [row["id"]]}, headers=O).json()
    assert d["missing"] == [], d["missing"]           # aucun [champ] laissé vide
    assert "[" not in d["body"] and "Atlas Logistique" in d["body"] and branch.split()[0].lower() in d["subject"].lower()
    assert "Valeur test" in d["body"] or "1 200 000" in d["body"]


def test_rename_dossier(client, world):  # noqa: F811
    client_co, _, _ = _setup()
    case = client.post("/api/quotes", json={"branch": "Automobile", "company_id": client_co}, headers=O).json()
    r = client.patch(f"/api/quotes/{case['id']}", json={"client_name": "Werin Group"}, headers=O)
    assert r.status_code == 200 and r.json()["client_name"] == "Werin Group"
    assert client.patch(f"/api/quotes/{case['id']}", json={"client_name": "  "}, headers=O).status_code == 422


def test_server_already_at_version_5_gets_the_new_templates(db):
    """Le serveur d'ODDO a déjà les modèles (version 5) : au démarrage, seuls C11 à C14 s'ajoutent."""
    from sqlalchemy import select

    from app import settings_store, starter_data
    from app.db import get_session
    from app.models import Sequence
    with get_session() as s:
        starter_data.apply_sequences(s)
        s.commit()
        for q in s.scalars(select(Sequence).where(Sequence.branch.in_(NEW))):
            s.delete(q)
        settings_store.set_(s, "starter_sequences_version", 5)
        s.commit()
        r = starter_data.apply_sequences(s)
        s.commit()
        assert r["sequences_created"] == 4
        assert {q.branch for q in s.scalars(select(Sequence).where(Sequence.name.like("C1_ ·%")))} >= set(NEW)

"""V3.11 : la page Entreprises (Commercial) sans les assureurs, qui ont leur page (Production)."""
from app.db import get_session
from app.models import Company


def test_companies_exclude_insurers(client, db):
    with get_session() as s:
        s.add_all([Company(name="Atlas Démo Assurances", name_key="atlas demo assurances", kind="insurer"),
                   Company(name="Sahel Négoce", name_key="sahel negoce", kind="prospect"),
                   Company(name="Riad Partenaire", name_key="riad partenaire", kind="partner")])
        s.commit()
    names = lambda **p: [c["name"] for c in client.get("/api/companies", params=p).json()["items"]]  # noqa: E731
    assert names(kind="insurer") == ["Atlas Démo Assurances"]
    assert names(exclude="insurer") == ["Sahel Négoce", "Riad Partenaire"]
    assert len(names()) == 3

"""V3.4 : variantes des textes par fonction / secteur (« Finance 2 »), choisies sur la fiche du
contact (FIN2-IND) ou par la campagne (remplacement ou partage A/B) ; texte générique pour les
contacts sans code ; les relances gardent les textes du 1er email ; statistiques par textes envoyés."""
from datetime import timedelta

from sqlalchemy import select

from app import stats
from app.db import get_session
from app.models import Campaign, ContentBlock, Contact, Enrollment, Message
from tests.test_m4_engine import ORIGIN, START, _activate, _run, world  # noqa: F401


def _block(client, kind, key):
    return next(b for b in client.get("/api/blocks").json() if b["kind"] == kind and b["key"] == key)


def test_variants_campaign_map_and_generic(client, world):  # noqa: F811
    camp_id = world["campaign_id"]
    with get_session() as s:  # textes génériques (données de départ « sequences.json » v5)
        s.add_all([ContentBlock(kind=k, key="ALL", body="Paragraphe ALL pour {{ entreprise }}.") for k in ("target", "sector")])
        s.commit()
    fin = _block(client, "target", "FIN")
    v = client.post(f"/api/blocks/{fin['id']}/variant", headers=ORIGIN).json()
    assert v["key"] == "FIN2" and v["variant_of"] == "FIN" and v["label"].endswith("· variante 2")
    client.put(f"/api/blocks/{v['id']}", json={"body": "Variante deux pour {{ entreprise }}."}, headers=ORIGIN)
    v3 = client.post(f"/api/blocks/{v['id']}/variant", headers=ORIGIN).json()   # variante d'une variante → FIN3
    assert v3["key"] == "FIN3" and v3["variant_of"] == "FIN"
    blocks = client.get("/api/blocks").json()
    assert [b["key"] for b in blocks if b["kind"] == "target"][:4] == ["FIN", "FIN2", "FIN3", "RH"]
    assert [b for b in blocks if b["key"] == "ALL" and b["kind"] == "target"][0]["generic"] is True

    with get_session() as s:
        s.add_all([Contact(email="daf2@usine.ma", first_name="Nadia", company="Usine Lourde", sequence_code="FIN2-IND",
                           email_reliability="Bonne (test)"),          # variante sur la fiche
                   Contact(email="sans.code@societe.ma", first_name="Karim", company="Sans Code SA",
                           email_reliability="Bonne (test)"),         # aucun code
                   Contact(email="daf3@usine.ma", first_name="Ali", company="Usine Trois", sequence_code="FIN-IND",
                           email_reliability="Bonne (test)")])
        s.commit()
    # la campagne remplace FIN par un partage FIN / FIN3, et IND par IND
    bad = client.put(f"/api/campaigns/{camp_id}/blocks", json={"target": {"FIN": "XYZ"}}, headers=ORIGIN)
    assert bad.status_code == 422
    r = client.put(f"/api/campaigns/{camp_id}/blocks", json={"target": {"FIN": ["FIN", "FIN3"], "RH": "RH"}}, headers=ORIGIN).json()
    assert r["block_map"] == {"target": {"FIN": ["FIN", "FIN3"]}}
    assert client.get(f"/api/campaigns/{camp_id}").json()["block_map"] == r["block_map"]
    with get_session() as s:
        s.get(ContentBlock, v3["id"]).body = "Variante trois pour {{ entreprise }}."
        s.commit()
    assert client.delete(f"/api/blocks/{v3['id']}", headers=ORIGIN).status_code == 409   # utilisée par la campagne

    assert _activate(camp_id) == 6
    _run(START + timedelta(days=1))
    with get_session() as s:
        firsts = {c.email: (m.body_text, e.block_code) for m, e, c in s.execute(
            select(Message, Enrollment, Contact).join(Enrollment, Enrollment.id == Message.enrollment_id)
            .join(Contact, Contact.id == Enrollment.contact_id)
            .where(Message.direction == "out", Message.step_position == 1))}
        assert len(firsts) == 6
        body, code = firsts["daf2@usine.ma"]
        assert "Variante deux pour Usine Lourde." in body and code is None          # fiche : FIN2, pas remplacé
        body, code = firsts["sans.code@societe.ma"]
        assert "Paragraphe ALL" in body and code is None                           # générique (sans code)
        fin_codes = [c for e, (b, c) in firsts.items() if e in ("contact0@societe0.ma", "daf3@usine.ma")]
        fin_bodies = {e: b for e, (b, c) in firsts.items() if e in ("contact0@societe0.ma", "daf3@usine.ma")}
        assert set(fin_codes) == {None, "FIN3-IND"}    # partage : l'un garde FIN (rien à mémoriser), l'autre FIN3
        assert any("Variante trois" in b for b in fin_bodies.values()) and any("Paragraphe FIN pour" in b for b in fin_bodies.values())
        segs = {r.key: r.reached for r in stats.by_segment(s, camp_id)}
        assert segs.get("FIN3-IND") == 1 and segs.get("FIN2-IND") == 1 and segs.get("FIN-IND") == 1
        # la campagne change ensuite : les relances gardent les textes du 1er email
    client.put(f"/api/campaigns/{camp_id}/blocks", json={"target": {"FIN": "FIN2"}}, headers=ORIGIN)
    with get_session() as s:
        e3 = s.scalars(select(Enrollment).where(Enrollment.block_code == "FIN3-IND")).one()
        assert e3.block_code == "FIN3-IND"
    up = client.get(f"/api/campaigns/{camp_id}/upcoming").json()
    nxt = {i["to"]: i["emails"] for i in up["items"]}
    assert all(not e["problems"] for emails in nxt.values() for e in emails)

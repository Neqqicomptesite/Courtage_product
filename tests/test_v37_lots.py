"""V3.7 : chaque import / recherche est un lot numéroté ; le lot n reçoit la variante n des textes."""
from sqlalchemy import select

from app import lists_service as ls
from app import sequences_service as ss
from app import vocab
from app.db import get_session
from app.models import Campaign, ContentBlock, Contact, Enrollment
from tests.test_m4_engine import ORIGIN, world  # noqa: F401


def test_resolve_code_follows_the_lot():
    keys = {"target": {"FIN", "FIN4", "DIR"}, "sector": {"BTP", "BTP4", "IND"}}
    assert ss.resolve_code(None, "FIN-BTP", 1, lot=4, keys=keys) == "FIN4-BTP4"
    assert ss.resolve_code(None, "DIR-IND", 1, lot=4, keys=keys) is None          # pas de variante 4 : textes d'origine
    assert ss.resolve_code(None, "FIN-IND", 1, lot=4, keys=keys) == "FIN4-IND"    # variante pour la fonction seulement
    assert ss.resolve_code(None, "FIN-BTP", 1, lot=1, keys=keys) is None           # lot 1 = textes d'origine
    assert ss.resolve_code({"target": {"FIN": "FIN2"}}, "FIN-BTP", 1, lot=4, keys=keys) == "FIN2-BTP4"  # choix de la campagne d'abord


def test_lots_are_numbered_and_keep_the_first_lot(world):  # noqa: F811
    with get_session() as s:
        ids = [c.id for c in s.scalars(select(Contact).order_by(Contact.id))]
        a = ls.create(s, "Import A", ids[:2], source="import")
        assert ls.stamp_lot(s, a, ids[:2]) == 1
        b = ls.create(s, "Import B", ids[1:3], source="import")
        assert ls.stamp_lot(s, b, ids[1:3]) == 2
        assert ls.stamp_lot(s, b, ids[1:3]) == 2                                    # même liste : même numéro
        lots = [s.get(Contact, i).lot_number for i in ids[:3]]
        assert lots == [1, 1, 2]                                                    # déjà au lot 1 : il y reste
        assert ls.stamp_lot(s, ls.create(s, "Vide", [], source="import"), []) is None  # rien de nouveau : pas de lot
        s.commit()


def test_campaign_shows_missing_lot_variant_and_creates_it(client, world):  # noqa: F811
    with get_session() as s:
        cs = list(s.scalars(select(Contact).order_by(Contact.id)))
        for c in cs:
            c.lot_number = 3
        code = cs[0].sequence_code
        s.commit()
    target, _, sector = code.partition("-")
    cid = world["campaign_id"]
    d = client.get(f"/api/campaigns/{cid}").json()
    lot3 = next(x for x in d["lot_texts"] if x["lot"] == 3)
    item = next(i for i in lot3["items"] if i["kind"] == "target" and i["root"] == target)
    assert item["key"] == f"{target}3" and item["block_id"] is None
    b = client.post(f"/api/blocks/{item['root_id']}/variant", json={"number": 3}, headers=ORIGIN).json()
    assert b["key"] == f"{target}3" and b["variant_of"] == target
    assert client.post(f"/api/blocks/{item['root_id']}/variant", json={"number": 3}, headers=ORIGIN).status_code == 422
    d = client.get(f"/api/campaigns/{cid}").json()
    item = next(i for i in next(x for x in d["lot_texts"] if x["lot"] == 3)["items"] if i["root"] == target)
    assert item["block_id"] == b["id"]
    with get_session() as s:  # au lancement, l'inscription garde la variante 3
        camp = s.get(Campaign, cid)
        c = s.get(Contact, cs[0].id)
        s.add(Enrollment(campaign_id=camp.id, contact_id=c.id, status="scheduled"))
        s.flush()
        ss.assign_codes(s, camp)
        enr = s.scalars(select(Enrollment).where(Enrollment.campaign_id == camp.id, Enrollment.contact_id == c.id)).first()
        assert enr.block_code.startswith(f"{target}3-")
        s.rollback()


def test_add_variant_with_number(world):  # noqa: F811
    with get_session() as s:
        fin = s.scalars(select(ContentBlock).where(ContentBlock.kind == "target", ContentBlock.key == "FIN")).first()
        assert vocab.add_variant(s, fin, 4).key == "FIN4"
        assert vocab.add_variant(s, fin).key == "FIN2"   # la suivante libre reste FIN2
        s.rollback()

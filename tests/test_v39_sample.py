"""V3.9 : « Aperçu des emails » avant de lancer une campagne : les vrais emails de quelques contacts."""
from sqlalchemy import select

from app import vocab
from app.db import get_session
from app.models import Campaign, ContentBlock, Contact
from tests.test_m4_engine import world  # noqa: F401


def test_sample_shows_real_emails_of_three_contacts(client, world):  # noqa: F811
    cid = world["campaign_id"]
    d = client.get(f"/api/campaigns/{cid}/sample").json()
    assert len(d["items"]) == 3 and d["test_mode"] is True
    it = d["items"][0]
    first = it["emails"][0]
    assert it["contact"]["first_name"] in first["body"] or it["contact"]["company"] in first["body"]  # personnalisé
    assert "Omar Douiri" in first["body"]                                                               # signature
    assert "[" not in first["subject"] and not first["problems"]
    assert [e["position"] for e in it["emails"]] == sorted(e["position"] for e in it["emails"])
    assert all(e["planned_at"] for e in it["emails"])
    assert d["from"]["email"]
    assert len(client.get(f"/api/campaigns/{cid}/sample?n=1").json()["items"]) == 1


def test_sample_picks_different_lots_and_uses_their_text(client, world):  # noqa: F811
    cid = world["campaign_id"]
    with get_session() as s:
        cs = list(s.scalars(select(Contact).order_by(Contact.id)))
        code = cs[0].sequence_code
        for c in cs:
            c.sequence_code = code
        cs[2].lot_number = 4
        target = code.partition("-")[0]
        root = s.scalars(select(ContentBlock).where(ContentBlock.kind == "target", ContentBlock.key == target)).first()
        v = vocab.add_variant(s, root, 4)
        v.body = "TEXTE SPECIAL DU LOT QUATRE"
        s.commit()
        lot4_email = cs[2].email
    d = client.get(f"/api/campaigns/{cid}/sample?n=2").json()
    emails = [x["to"] for x in d["items"]]
    assert lot4_email in emails                      # deux lots différents : un contact de chacun
    lot4 = next(x for x in d["items"] if x["to"] == lot4_email)
    assert lot4["lot"] == 4 and lot4["code"].startswith(f"{target}4-")
    assert any("TEXTE SPECIAL DU LOT QUATRE" in e["body"] for e in lot4["emails"])
    other = next(x for x in d["items"] if x["to"] != lot4_email)
    assert not any("TEXTE SPECIAL DU LOT QUATRE" in e["body"] for e in other["emails"])


def test_sample_only_for_drafts_and_skips_excluded(client, world):  # noqa: F811
    cid = world["campaign_id"]
    with get_session() as s:
        c = s.scalars(select(Contact).order_by(Contact.id)).first()
        c.global_status = "unsubscribed"
        s.commit()
        gone = c.email
    d = client.get(f"/api/campaigns/{cid}/sample?n=10").json()
    assert gone not in [x["to"] for x in d["items"]] and len(d["items"]) == 2
    with get_session() as s:
        s.get(Campaign, cid).status = "active"
        s.commit()
    assert client.get(f"/api/campaigns/{cid}/sample").status_code == 400


def test_sample_is_what_will_really_leave(client, world):  # noqa: F811
    """Après le lancement, « À venir » montre exactement les emails de l'aperçu."""
    from tests.test_m4_engine import ORIGIN
    cid = world["campaign_id"]
    before = {x["to"]: x for x in client.get(f"/api/campaigns/{cid}/sample?n=10").json()["items"]}
    assert client.post(f"/api/campaigns/{cid}/activate", json={}, headers=ORIGIN).status_code == 200
    after = {x["to"]: x for x in client.get(f"/api/campaigns/{cid}/upcoming").json()["items"]}
    assert set(before) == set(after)
    for to, x in before.items():
        assert len(x["emails"]) == len(after[to]["emails"])
        for a, b in zip(x["emails"], after[to]["emails"]):
            assert a["body"] == b["body"]
            if x["variant"] == after[to]["variant"]:  # objet A/B : tiré au sort au lancement
                assert a["subject"] == b["subject"]
    variants = {x["variant"] for x in before.values()}
    assert len(variants) == 2  # l'aperçu montre les deux objets du test A/B

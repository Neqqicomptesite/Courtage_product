"""V3.7 : suggestions d'adresses (À / Cc / Cci) et copie cachée."""
from sqlalchemy import select

from app import address_book, manual_mail
from app.db import get_session
from app.models import AddressBook, Contact
from tests.test_m4_engine import ORIGIN, world  # noqa: F401


def test_suggestions_come_from_contacts_sent_and_seen(client, world):  # noqa: F811
    with get_session() as s:
        s.add(Contact(email="yassine.laoud@assureur-demo.test", first_name="Yassine", last_name="Laoud", company="Assureur Démo", kind="insurer"))
        s.commit()
        address_book.record_sent(s, ["yasmine.k@cabinet-demo.test", "yasmine.k@cabinet-demo.test"])  # même email : 1 fois
        s.commit()
        address_book.record_sent(s, ["yasmine.k@cabinet-demo.test"])
        s.commit()
    address_book.record_seen([("Yassir Benali", "yassir@client-demo.test"), ("Lettre", "news@robot-demo.test")], own={"moi@oddo.test"})
    items = client.get("/api/mailbox/suggest?q=yas").json()["items"]
    emails = [i["email"] for i in items]
    assert set(emails) >= {"yassine.laoud@assureur-demo.test", "yasmine.k@cabinet-demo.test", "yassir@client-demo.test"}
    assert emails[0] == "yasmine.k@cabinet-demo.test"  # déjà écrit 2 fois : en tête
    yassine = next(i for i in items if i["email"].startswith("yassine"))
    assert yassine["name"] == "Yassine Laoud" and yassine["company"] == "Assureur Démo"
    assert next(i for i in items if i["email"].startswith("yassir"))["name"] == "Yassir Benali"
    # par le nom de famille, sans accent, et en excluant ceux déjà choisis
    assert [i["email"] for i in client.get("/api/mailbox/suggest?q=laoud").json()["items"]] == ["yassine.laoud@assureur-demo.test"]
    assert "yasmine.k@cabinet-demo.test" not in [i["email"] for i in client.get(
        "/api/mailbox/suggest?q=yas&exclude=yasmine.k@cabinet-demo.test").json()["items"]]
    assert client.get("/api/mailbox/suggest?q=y").json()["items"] == []
    with get_session() as s:  # un expéditeur déjà connu n'est pas réécrit
        n = s.scalar(select(AddressBook.uses).where(AddressBook.email == "yasmine.k@cabinet-demo.test"))
        assert n == 2


def test_bcc_is_sent_but_hidden(world):  # noqa: F811
    d = manual_mail.draft_from({"to": "a@demo.test", "cc": ["b@demo.test", "c@demo.test"], "bcc": "d@demo.test; e@demo.test",
                                "subject": "x", "body": "y"})
    assert d.cc == ["b@demo.test", "c@demo.test"] and d.bcc == ["d@demo.test", "e@demo.test"]
    bad = manual_mail.draft_from({"to": "a@demo.test", "bcc": "pas-une-adresse", "body": "y"})
    with get_session() as s:
        try:
            manual_mail.validate(s, bad)
            raise AssertionError("adresse Cci invalide acceptée")
        except manual_mail.SendRefused as exc:
            assert "pas-une-adresse" in str(exc)


def test_bcc_reaches_smtp_without_header(client, world):  # noqa: F811
    from app import settings_store
    with get_session() as s:
        settings_store.set_(s, "test_mode", False)
        s.commit()
    r = client.post("/api/mailbox/send", json={"to": "contact0@societe0.ma", "cc": "b@demo.test", "bcc": "cache@demo.test",
                                                "subject": "Copie cachée", "body": "Bonjour."}, headers=ORIGIN)
    assert r.status_code == 200, r.text
    (sent,) = world["smtp"].messages
    assert sorted(sent.rcpt_tos) == ["b@demo.test", "cache@demo.test", "contact0@societe0.ma"]
    data = sent.data.decode() if isinstance(sent.data, bytes) else sent.data
    assert "cache@demo.test" not in data and "Cc: b@demo.test" in data
    with get_session() as s:  # les 3 adresses entrent dans le carnet
        assert {"b@demo.test", "cache@demo.test", "contact0@societe0.ma"} <= set(s.scalars(select(AddressBook.email)))

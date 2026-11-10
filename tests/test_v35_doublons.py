"""V3.5 : ne pas envoyer deux séquences à la même personne.

- en cours dans une autre campagne : vu aussi chez les collègues (avant : seulement les siennes) ;
- déjà prospecté il y a moins de 90 jours (réglable) sans répondre : mis de côté, forçable ;
- les sans-réponse d'une campagne : filtre « no_reply_of » pour les relancer plus tard ;
- rebond : date sur la fiche, et nouvelle fiche avec la bonne adresse.
"""
from datetime import timedelta

import pytest
from sqlalchemy import select

from app import campaigns_service as camp_svc
from app import contacts_service as cs
from app import settings_store
from app.current import as_user
from app.db import get_session
from app.models import AppUser, Campaign, Contact, Enrollment, Mailbox, Message, Sequence
from tests.test_m4_engine import ORIGIN, START, world  # noqa: F401


def _cands(camp_id, now=START):
    with get_session() as s:
        return {c.contact.email: c for c in camp_svc.candidates(s, s.get(Campaign, camp_id), check_render=False, now=now)}


def _second_campaign(s, mailbox_id=None, status="active"):
    mb = mailbox_id or s.scalars(select(Mailbox.id)).first()
    seq = s.scalars(select(Sequence.id)).first()
    camp = Campaign(name="P1 DIR", mailbox_id=mb, sequence_id=seq, filters={}, status=status)
    s.add(camp)
    s.flush()
    return camp


def test_recently_prospected_put_aside_then_forceable(world):
    with get_session() as s:
        other = _second_campaign(s, status="finished")
        c0 = s.scalars(select(Contact).where(Contact.email == "contact0@societe0.ma")).one()
        c1 = s.scalars(select(Contact).where(Contact.email == "contact1@societe1.ma")).one()
        e0 = Enrollment(campaign_id=other.id, contact_id=c0.id, status="completed")
        e1 = Enrollment(campaign_id=other.id, contact_id=c1.id, status="completed")
        s.add_all([e0, e1])
        s.flush()
        mb = s.scalars(select(Mailbox.id)).first()
        s.add(Message(enrollment_id=e0.id, contact_id=c0.id, mailbox_id=mb, direction="out", step_position=3,
                      sent_at=START - timedelta(days=20), message_id="<a@x>"))
        # un essai en mode test ne compte pas, ni un email d'il y a plus de 90 jours
        s.add(Message(enrollment_id=e1.id, contact_id=c1.id, mailbox_id=mb, direction="out", step_position=1,
                      sent_at=START - timedelta(days=5), message_id="<b@x>", test_mode=True))
        s.add(Message(enrollment_id=e1.id, contact_id=c1.id, mailbox_id=mb, direction="out", step_position=3,
                      sent_at=START - timedelta(days=100), message_id="<c@x>"))
        s.commit()
    c = _cands(world["campaign_id"])
    assert c["contact0@societe0.ma"].recent.startswith("Dernier email le ")
    assert "relançable à partir du" in c["contact0@societe0.ma"].recent
    assert c["contact1@societe1.ma"].recent is None and c["contact2@societe2.ma"].recent is None
    with get_session() as s:
        camp = s.get(Campaign, world["campaign_id"])
        r = camp_svc.activation_report(s, camp, include_overlapping=False, now=START)
        assert [x.contact.email for x in r.recent] == ["contact0@societe0.ma"] and len(r.eligible) == 2
        r = camp_svc.activation_report(s, camp, include_overlapping=False, now=START, include_recent=True)
        assert len(r.eligible) == 3
        settings_store.set_(s, "reprospect_days", 10)  # règle réglable : à 10 jours, il redevient prospectable
        s.commit()
    assert _cands(world["campaign_id"])["contact0@societe0.ma"].recent is None


def test_busy_in_a_colleague_campaign_is_seen(world):
    with get_session() as s:
        k = AppUser(email="karim@oddo.ma", full_name="Karim Alaoui", role="user", active=True)
        o = AppUser(email="omar@oddo.ma", full_name="Omar Douiri", role="admin", active=True)
        s.add_all([k, o])
        s.flush()
        s.scalars(select(Mailbox)).first().user_id = o.id
        mb_k = Mailbox(display_name="Karim", email="karim@oddo.ma", user_id=k.id)
        s.add(mb_k)
        s.flush()
        other = _second_campaign(s, mailbox_id=mb_k.id)
        c2 = s.scalars(select(Contact).where(Contact.email == "contact2@societe2.ma")).one()
        s.add(Enrollment(campaign_id=other.id, contact_id=c2.id, status="waiting"))
        s.commit()
        omar_id = o.id
    from app import scope
    scope.forget_cache()
    with as_user(omar_id, "admin"):
        c = _cands(world["campaign_id"])
    assert c["contact2@societe2.ma"].other_campaigns == ["une campagne de Karim"]  # nom de sa campagne : privé
    with as_user(omar_id, "admin"), get_session() as s:
        camp = s.get(Campaign, world["campaign_id"])
        c2 = s.scalars(select(Contact).where(Contact.email == "contact2@societe2.ma")).one()
        with pytest.raises(camp_svc.EnrollRefused):
            camp_svc.enroll_one(s, camp, c2)


def test_no_reply_filter_and_summary(world, client):
    with get_session() as s:
        camp = s.get(Campaign, world["campaign_id"])
        camp.status = "finished"
        rows = {c.email: c for c in s.scalars(select(Contact))}
        statuses = {"contact0@societe0.ma": "completed", "contact1@societe1.ma": "replied", "contact2@societe2.ma": "completed"}
        for email, st in statuses.items():
            e = Enrollment(campaign_id=camp.id, contact_id=rows[email].id, status=st)
            s.add(e)
            s.flush()
            s.add(Message(enrollment_id=e.id, contact_id=rows[email].id, mailbox_id=camp.mailbox_id, direction="out",
                          step_position=3, sent_at=START, message_id=f"<{email}>"))
        rows["contact2@societe2.ma"].global_status = "bounced"  # plus joignable : pas compté
        s.commit()
        found = {c.email for c in s.scalars(cs.filtered_query(cs.ContactFilters(no_reply_of=str(camp.id))))}
        assert found == {"contact0@societe0.ma", "contact2@societe2.ma"}  # le filtre ; le statut écarte au lancement
        summ = camp_svc.no_reply_summary(s, camp)
        assert summ["count"] == 1 and summ["days"] == 90
        assert summ["relaunch_from"].startswith(str((START + timedelta(days=90)).date()))
    n = client.get(f"/api/contacts/count?no_reply_of={world['campaign_id']}").json()
    assert n["matching"] == 2 and n["active"] == 1  # le compteur de l'assistant suit le filtre
    d = client.get(f"/api/campaigns/{world['campaign_id']}").json()
    assert d["no_reply"]["count"] == 1
    assert "no_reply_of" in camp_svc.FILTER_KEYS


def test_bounce_date_and_new_address(world, client):
    with get_session() as s:
        c = s.scalars(select(Contact).where(Contact.email == "contact0@societe0.ma")).one()
        c.global_status = "bounced"
        c.custom = {"accroche": "x"}
        s.add(Message(contact_id=c.id, direction="in", kind="bounce_hard", received_at=START, message_id="<dsn@x>"))
        s.commit()
        cid = c.id
    d = client.get(f"/api/contacts/{cid}").json()
    assert d["bounced_at"] and d["status"] == "bounced"
    r = client.post(f"/api/contacts/{cid}/new-address", json={"email": "Prenom0@Societe0.ma"}, headers=ORIGIN)
    assert r.status_code == 200
    with get_session() as s:
        new = s.get(Contact, r.json()["id"])
        assert new.email == "prenom0@societe0.ma" and new.global_status == "active"
        assert (new.first_name, new.company, new.sequence_code, new.custom) == ("Prénom0", "Société 0", "FIN-IND", {"accroche": "x"})
        assert s.get(Contact, cid).global_status == "bounced"
    assert client.post(f"/api/contacts/{cid}/new-address", json={"email": "prenom0@societe0.ma"},
                       headers=ORIGIN).status_code == 409  # adresse déjà prise


def test_rename_campaign(world, client):
    r = client.put(f"/api/campaigns/{world['campaign_id']}/name", json={"name": "  Campagne   BTP "}, headers=ORIGIN)
    assert r.status_code == 200 and r.json()["name"] == "Campagne BTP"
    assert client.get(f"/api/campaigns/{world['campaign_id']}").json()["name"] == "Campagne BTP"
    assert client.put(f"/api/campaigns/{world['campaign_id']}/name", json={"name": "   "}, headers=ORIGIN).status_code == 422
    assert client.put("/api/campaigns/999/name", json={"name": "X"}, headers=ORIGIN).status_code == 404

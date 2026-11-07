"""M3 : rendu des modèles, composition des emails, planification, A/B, pages Séquences."""
import random
import re
from collections import Counter
from datetime import date, datetime, time, timezone
from email import message_from_bytes
from email.header import decode_header, make_header

import pytest
from sqlalchemy import select

from app import render
from app.ab_testing import assign_variants
from app.db import get_session
from app.mail import compose
from app.models import ContentBlock, Contact, Sequence, Step, StepVariant
from app.scheduling import SendWindow, planned_dates
from tests.conftest import PASSWORD, USER

UTC = timezone.utc
ORIGIN = {"Origin": "http://testserver"}


def _contact(**kw):
    base = dict(email="khaoula@3s.ma", first_name="Khaoula", last_name="Rouissi", company="3S Morocco",
                job_title="DAF", sector="EPI", sequence_code="FIN-IND",
                custom={"accroche_suggeree": "Revue gratuite"})
    base.update(kw)
    return Contact(**base)


def _ctx(contact=None, target=None, sector=None, signature="Omar Douiri\nODDO Assurance"):
    return render.RenderContext(
        contact=contact or _contact(), signature=signature,
        target_blocks=target if target is not None else {"FIN": "Trame finance pour {{ entreprise }}.", "RH": "Trame RH."},
        sector_blocks=sector if sector is not None else {"IND": "Paragraphe industrie.", "BTP": "Paragraphe BTP."})


# ------------------------------------------------------------------- rendu

def test_variables_custom_and_blocks():
    r = render.render("Bonjour {{ prenom }},\n\n{{ bloc_cible }}\n\n{{ bloc_secteur }}\n\n{{ custom.accroche_suggeree }}",
                      _ctx())
    assert r.ok, r.problems
    assert r.text == ("Bonjour Khaoula,\n\nTrame finance pour 3S Morocco.\n\n"
                      "Paragraphe industrie.\n\nRevue gratuite")


def test_blocks_follow_sequence_code():
    r = render.render("{{ bloc_cible }} / {{ bloc_secteur }}", _ctx(_contact(sequence_code="RH-BTP")))
    assert r.text == "Trame RH. / Paragraphe BTP."


def test_fallback_value():
    r = render.render('Bonjour {{ prenom | "Madame, Monsieur" }},', _ctx(_contact(first_name=None)))
    assert r.ok and r.text == "Bonjour Madame, Monsieur,"
    r = render.render('Bonjour {{ prenom | "Madame, Monsieur" }},', _ctx())
    assert r.text == "Bonjour Khaoula,"


@pytest.mark.parametrize("template, expected", [
    ("{{ prenom }}", "Valeur manquante pour {{ prenom }}"),
    ("{{ telephone }}", "Variable inconnue : {{ telephone }}"),
    ("{{ custom.inexistant }}", "Valeur manquante pour {{ custom.inexistant }}"),
    ("Bonjour {{ prenom }", "Variable mal écrite"),
    ("{{ pré nom }}", "Variable mal écrite"),
])
def test_unresolved_variables_are_reported(template, expected):
    r = render.render(template, _ctx(_contact(first_name="")))
    assert not r.ok
    assert any(expected in p for p in r.problems), r.problems


def test_missing_or_unwritten_blocks_are_reported():
    r = render.render("{{ bloc_cible }}{{ bloc_secteur }}", _ctx(_contact(sequence_code="DIR-SANTE")))
    assert "Bloc cible « DIR » introuvable" in r.problems
    assert "Bloc secteur « SANTE » introuvable" in r.problems
    r = render.render("{{ bloc_cible }}", _ctx(target={"FIN": "À RÉDIGER – trame"}))
    assert any("pas encore rédigé" in p for p in r.problems)
    r = render.render("{{ bloc_cible }}", _ctx(_contact(sequence_code=None)))
    assert any("Code séquence absent" in p for p in r.problems)


def test_empty_block_does_not_leave_big_gaps():
    r = render.render("A\n\n{{ bloc_secteur }}\n\nB", _ctx(sector={"IND": ""}))
    assert r.text == "A\n\nB"


def test_full_body_adds_signature_once_and_always_stop_line():
    body = render.full_body("Corps", "Corps", "Omar", "Répondez STOP.")
    assert body == "Corps\n\nOmar\n\nRépondez STOP."
    body = render.full_body("Corps\nOmar", "Corps\n{{ signature }}", "Omar", "Répondez STOP.")
    assert body.count("Omar") == 1 and body.endswith("Répondez STOP.")


def test_reply_subject():
    assert render.subject_for_reply("Vos assurances") == "Re: Vos assurances"
    assert render.subject_for_reply("Re: Vos assurances") == "Re: Vos assurances"


# ---------------------------------------------------------------- composition

def test_message_headers_threading_and_utf8():
    root = compose.new_message_id("o.douiri@oddo.ma")
    assert root.endswith("@oddo.ma>")
    msg = compose.build_message(
        from_name="Omar Douiri", from_email="o.douiri@oddo.ma", to_email="k@3s.ma",
        subject="Re: Révision de vos contrats – été", body="Bonjour Réda,\nÀ bientôt — Omar",
        message_id=compose.new_message_id("o.douiri@oddo.ma"), in_reply_to=root, references=[root])
    parsed = message_from_bytes(msg.as_bytes())
    assert str(make_header(decode_header(parsed["Subject"]))) == "Re: Révision de vos contrats – été"
    assert parsed["In-Reply-To"] == root and parsed["References"] == root
    assert parsed["List-Unsubscribe"] == "<mailto:o.douiri@oddo.ma?subject=STOP>"
    assert parsed.get_content_type() == "text/plain"
    assert parsed.get_content_charset() == "utf-8"
    assert parsed.get_payload(decode=True).decode("utf-8") .startswith("Bonjour Réda,\nÀ bientôt — Omar")
    assert "Omar Douiri" in parsed["From"]


def test_test_mode_subject():
    assert compose.test_mode_subject("Objet", "k@3s.ma") == "[TEST → k@3s.ma] Objet"


# ---------------------------------------------------------------- planification

def _window(holidays=()):
    return SendWindow(days=frozenset({0, 1, 2, 3, 4}),
                      ranges=((time(9, 0), time(12, 30)), (time(14, 30), time(17, 30))),
                      holidays=frozenset(holidays))


def _utc(local_iso):
    """Heure locale du Maroc -> UTC (via tzdata, jamais d'écart codé en dur)."""
    from app.timeutil import TZ
    return datetime.fromisoformat(local_iso).replace(tzinfo=TZ).astimezone(UTC)


def _loc(dt):
    from app.timeutil import to_local
    return to_local(dt).strftime("%Y-%m-%d %H:%M")


def test_next_open_respects_windows_weekends_and_holidays():
    w = _window(holidays={date(2026, 11, 18)})
    assert _loc(w.next_open(_utc("2026-11-03T08:00"))) == "2026-11-03 09:00"   # avant l'ouverture
    assert _loc(w.next_open(_utc("2026-11-03T10:15"))) == "2026-11-03 10:15"   # déjà ouvert
    assert _loc(w.next_open(_utc("2026-11-03T13:00"))) == "2026-11-03 14:30"   # pause déjeuner
    assert _loc(w.next_open(_utc("2026-11-03T17:30"))) == "2026-11-04 09:00"   # fermeture
    assert _loc(w.next_open(_utc("2026-11-06T18:00"))) == "2026-11-09 09:00"   # vendredi soir -> lundi
    assert _loc(w.next_open(_utc("2026-11-17T18:00"))) == "2026-11-19 09:00"   # 18/11 férié


def test_business_days_skip_weekend_and_holidays():
    w = _window(holidays={date(2026, 11, 18)})
    assert w.add_days(date(2026, 11, 13), 3, business=True) == date(2026, 11, 19)  # ven -> lun, mar, (mer férié), jeu
    assert w.add_days(date(2026, 11, 13), 3, business=False) == date(2026, 11, 16)


def test_planned_dates_for_default_sequence():
    w = _window()
    steps = [Step(position=1, delay_days=0, business_days=True), Step(position=2, delay_days=3, business_days=True),
             Step(position=3, delay_days=4, business_days=True)]
    dates = planned_dates(w, _utc("2026-11-05T16:00"), steps)  # jeudi 16:00
    assert [_loc(d) for d in dates] == ["2026-11-05 16:00", "2026-11-10 09:00", "2026-11-16 09:00"]


def test_send_window_follows_morocco_time_changes():
    """L'heure légale du Maroc change (Ramadan) : 09:00 locale n'a pas toujours le même écart UTC.
    On vérifie que la fenêtre suit l'heure LOCALE, quel que soit l'écart du jour."""
    from zoneinfo import ZoneInfo
    tz = ZoneInfo("Africa/Casablanca")
    offsets = {}
    d = date(2026, 1, 5)
    while d < date(2027, 12, 31):
        offsets.setdefault(datetime.combine(d, time(12), tz).utcoffset(), d)
        d = d.fromordinal(d.toordinal() + 7)
    assert len(offsets) >= 2, "tzdata ne contient pas de changement d'heure : test impossible"
    w = _window()
    for offset, day in offsets.items():
        monday = day.fromordinal(day.toordinal() - day.weekday())
        opened = w.next_open(datetime.combine(monday, time(0), tz).astimezone(UTC))
        assert _loc(opened).endswith("09:00")
        assert opened.hour == (9 - int(offset.total_seconds() // 3600)) % 24


# ------------------------------------------------------------------------ A/B

def test_ab_split_exact_and_stable():
    ids = list(range(1, 101))
    first = assign_variants(ids, ["A", "B"], rng=random.Random(42))
    assert Counter(first.values()) == {"A": 50, "B": 50}
    # Ajout de 7 contacts plus tard : les anciens ne bougent pas, l'équilibre est maintenu.
    more = assign_variants(list(range(101, 108)), ["A", "B"], existing=Counter(first.values()),
                           rng=random.Random(1))
    assert set(more).isdisjoint(first)
    total = Counter(first.values()) + Counter(more.values())
    assert abs(total["A"] - total["B"]) <= 1
    # Le tirage est bien aléatoire : une autre graine donne une autre répartition.
    other = assign_variants(ids, ["A", "B"], rng=random.Random(7))
    assert other != first


def test_ab_single_variant():
    assert set(assign_variants([1, 2, 3], ["A"]).values()) == {"A"}


# --------------------------------------------------------------- pages web

def _seed_contacts(codes=("FIN-IND", "RH-BTP")):
    with get_session() as s:
        for st in s.scalars(select(Step)):  # les relances d'exemple contiennent « À RÉDIGER »
            st.body_template = st.body_template.replace("À RÉDIGER", "Texte rédigé")
        for i, code in enumerate(codes):
            s.add(Contact(email=f"c{i}@entreprise{i}.ma", first_name=f"Prénom{i}", last_name="Test",
                          company=f"Entreprise {i}", sequence_code=code))
        for b in s.scalars(select(ContentBlock)):
            b.body = f"Texte du bloc {b.key} pour {{{{ entreprise }}}}."
        s.commit()
        return [c.id for c in s.scalars(select(Contact).order_by(Contact.id))]


def _seq_id():
    with get_session() as s:
        return s.scalars(select(Sequence.id)).first()


def test_preview_fin_ind_shows_right_blocks(client):
    """Critère d'acceptation M3 n°1."""
    ids = _seed_contacts()
    page = client.get(f"/sequences/{_seq_id()}/preview?contact_id={ids[0]}").text
    assert "Texte du bloc FIN pour Entreprise 0." in page
    assert "Texte du bloc IND pour Entreprise 0." in page
    assert "Texte du bloc RH" not in page and "Texte du bloc BTP" not in page
    assert "Aucun problème" in page
    assert "Répondez simplement « STOP »" in page or "répondez simplement « STOP »" in page
    assert re.search(r"prévue le (lundi|mardi|mercredi|jeudi|vendredi) \d\d/\d\d/\d{4} à \d\d:\d\d", page)
    assert "Re: Entreprise 0 : vos contrats d&#39;assurance" in page or "Re: Question rapide sur vos assurances" in page


def test_preview_flags_missing_variable(client):
    """Critère d'acceptation M3 n°2."""
    ids = _seed_contacts()
    with get_session() as s:
        st = s.scalars(select(Step).where(Step.position == 1)).first()
        st.body_template = "Bonjour {{ prenom }}, {{ custom.accroche_suggeree }}"
        s.commit()
    page = client.get(f"/sequences/{_seq_id()}/preview?contact_id={ids[0]}").text
    assert "Valeur manquante pour {{ custom.accroche_suggeree }}" in page
    assert "problème(s) à corriger" in page


def test_todo_marker_in_step_text_is_reported(client):
    ids = _seed_contacts()
    with get_session() as s:
        s.scalars(select(Step).where(Step.position == 2)).first().body_template = "À RÉDIGER : relance"
        s.commit()
    page = client.get(f"/sequences/{_seq_id()}/preview?contact_id={ids[0]}").text
    assert "Le texte de l&#39;étape contient encore « À RÉDIGER »" in page or \
           "Le texte de l'étape contient encore « À RÉDIGER »" in page
    assert "Aucun problème" not in page


def test_seeded_blocks_are_reported_as_todo(client):
    ids = _seed_contacts()
    with get_session() as s:
        s.scalars(select(ContentBlock).where(ContentBlock.key == "IND")).one().body = "À RÉDIGER"
        s.commit()
    page = client.get(f"/sequences/{_seq_id()}/preview?contact_id={ids[0]}").text
    assert "pas encore rédigé" in page
    assert "bloc(s) encore à rédiger : IND" in client.get("/sequences").text


def test_edit_sequence_subjects_ab_and_steps(client):
    seq_id = _seq_id()
    page = client.get(f"/sequences/{seq_id}").text
    steps = [int(x) for x in re.findall(r'name="(\d+)_body"', page)]
    assert len(steps) == 3 and "J+7 ouvrés depuis l'étape 1" in page
    data = {"name": "Prospection PME v2",
            f"{steps[0]}_subject_A": "Objet A", f"{steps[0]}_subject_B": "",  # B retiré
            f"{steps[0]}_body": "Corps 1", f"{steps[0]}_business": "on",
            f"{steps[1]}_delay": "2", f"{steps[1]}_business": "on", f"{steps[1]}_thread": "on", f"{steps[1]}_body": "Corps 2",
            f"{steps[2]}_delay": "5", f"{steps[2]}_body": "Corps 3", f"{steps[2]}_subject_A": "Nouveau fil"}
    r = client.post(f"/sequences/{seq_id}", data=data, headers=ORIGIN)
    assert "Séquence enregistrée" in r.text
    with get_session() as s:
        sts = s.scalars(select(Step).where(Step.sequence_id == seq_id).order_by(Step.position)).all()
        assert [st.delay_days for st in sts] == [0, 2, 5]
        assert [st.same_thread for st in sts] == [False, True, False]
        assert sts[2].business_days is False
        labels = {(v.step_id, v.label, v.subject_template) for v in s.scalars(select(StepVariant))}
        assert (sts[0].id, "A", "Objet A") in labels and not any(l == "B" for _, l, _ in labels)
        assert (sts[2].id, "A", "Nouveau fil") in labels

    client.post(f"/sequences/{seq_id}/steps/add", headers=ORIGIN)
    client.post(f"/sequences/{seq_id}/steps/{steps[1]}/delete", headers=ORIGIN)
    with get_session() as s:
        positions = [st.position for st in s.scalars(select(Step).where(Step.sequence_id == seq_id).order_by(Step.position))]
        assert positions == [1, 2, 3]


def test_first_step_cannot_be_deleted(client):
    seq_id = _seq_id()
    with get_session() as s:
        first = s.scalars(select(Step).where(Step.sequence_id == seq_id, Step.position == 1)).one().id
    r = client.post(f"/sequences/{seq_id}/steps/{first}/delete", headers=ORIGIN)
    assert "ne peut pas être supprimée" in r.text


def test_create_sequence_has_default_steps(client):
    r = client.post("/sequences/new", data={"name": "Relance clients"}, headers=ORIGIN)
    assert r.status_code == 200 and "Relance clients" in r.text
    assert "J+3 ouvrés" in r.text and "J+7 ouvrés" in r.text


def test_block_edit(client):
    page = client.get("/sequences/blocks").text
    block_id = re.search(r'action="/sequences/blocks/(\d+)"', page).group(1)
    r = client.post(f"/sequences/blocks/{block_id}", data={"body": "Nouveau texte FIN"}, headers=ORIGIN)
    assert "Bloc FIN enregistré" in r.text and "Nouveau texte FIN" in r.text


def test_send_preview_goes_only_to_omar_in_one_thread(client, smtp_ssl):
    ids = _seed_contacts()
    client.post("/settings/mailbox", headers=ORIGIN, data={
        "display_name": "Omar Douiri", "email": USER, "smtp_host": "127.0.0.1", "smtp_port": str(smtp_ssl.port),
        "smtp_security": "ssl", "imap_host": "127.0.0.1", "imap_port": "993", "username": USER,
        "password": PASSWORD, "signature": "Omar"})
    r = client.post(f"/sequences/{_seq_id()}/preview/send", data={"contact_id": ids[0], "variant": "B"},
                    headers=ORIGIN)
    assert "3 email(s) d&#39;aperçu envoyé(s)" in r.text or "3 email(s) d'aperçu envoyé(s)" in r.text
    assert len(smtp_ssl.messages) == 3
    assert all(m.rcpt_tos == [USER] for m in smtp_ssl.messages)  # jamais au contact
    msgs = [message_from_bytes(m.data) for m in smtp_ssl.messages]
    subjects = [str(make_header(decode_header(m["Subject"]))) for m in msgs]
    assert subjects[0] == "[APERÇU → c0@entreprise0.ma] [Étape 1] Question rapide sur vos assurances"
    assert subjects[1].endswith("Re: Question rapide sur vos assurances")
    assert msgs[1]["In-Reply-To"] == msgs[0]["Message-ID"]
    # Un en-tête long peut être « replié » sur plusieurs lignes (norme RFC 5322) : on normalise les espaces.
    assert " ".join(msgs[2]["References"].split()) == f'{msgs[0]["Message-ID"]} {msgs[1]["Message-ID"]}'

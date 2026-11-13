"""V3.11.1 (13/11) : une relance est partie avec « Revue gratuite … des primesBonjour Fatiha » : une colonne
importée ({{ custom.… }}) insérée au tout début du texte, collée à « Bonjour ». Plus jamais : bloquant."""
from datetime import timedelta

from sqlalchemy import select

from app import campaigns_service as camp_svc
from app import sequences_service as ss
from app.db import get_session
from app.models import Campaign, Contact, Enrollment, Message, Step
from tests.test_m4_engine import START, _activate, _run, world  # noqa: F401

BAD = '{{ custom.garanties_a_evoquer_pistes }}Bonjour {{ prenom | "Madame, Monsieur" }},\n\nJe me permets de revenir vers vous.'


def test_checks():
    assert ss.template_problems(BAD) and "collée" in ss.template_problems(BAD)[0]
    assert any("commence par {{ custom.garanties_a_evoquer_pistes }}" in w for w in ss.template_warnings(BAD))
    ok = 'Bonjour {{ prenom }},\n\nVotre entreprise {{ entreprise }} (réf. {{ custom.ref }}).\n\nM.{{ nom }}, l\'{{ entreprise }}'
    assert ss.template_problems(ok) == [] and ss.template_warnings(ok) == []
    assert ss.template_problems("Voir la société{{ entreprise }}")


def _break_step2(campaign_id):
    with get_session() as s:
        camp = s.get(Campaign, campaign_id)
        st = s.scalars(select(Step).where(Step.sequence_id == camp.sequence_id, Step.position == 2)).one()
        st.body_template = BAD
        for c in s.scalars(select(Contact)):
            c.custom = {**(c.custom or {}), "garanties_a_evoquer_pistes": "Revue gratuite des contrats"}
        s.commit()


def test_launch_refused_with_a_glued_variable(world):  # noqa: F811
    _break_step2(world["campaign_id"])
    with get_session() as s:
        r = camp_svc.activation_report(s, s.get(Campaign, world["campaign_id"]), include_overlapping=True)
        assert r.blocked and any("collée" in p for c in r.with_problems for p in c.problems)
        assert any("commence par" in w for w in r.link_warnings)


def test_running_campaign_never_sends_the_broken_follow_up(world):  # noqa: F811
    _activate(world["campaign_id"])
    _run(until=START + timedelta(hours=3))              # 1er email parti, texte encore correct
    _break_step2(world["campaign_id"])                  # quelqu'un abîme la relance pendant la campagne
    _run(until=START + timedelta(days=14))
    with get_session() as s:
        relances = s.scalars(select(Message).where(Message.direction == "out", Message.step_position == 2)).all()
        assert relances == []
        errs = s.scalars(select(Enrollment).where(Enrollment.status == "error")).all()
        assert errs and all("collée" in (e.last_error or "") for e in errs)


def test_glued_variable_inside_a_function_text_blocks_too(world):  # noqa: F811
    from app.models import ContentBlock
    with get_session() as s:
        c = s.scalars(select(Contact).order_by(Contact.id)).first()
        target = c.sequence_code.partition("-")[0]
        b = s.scalars(select(ContentBlock).where(ContentBlock.kind == "target", ContentBlock.key == target)).one()
        b.body = "Pour {{ entreprise }}nous proposons une revue."
        s.commit()
        r = camp_svc.activation_report(s, s.get(Campaign, world["campaign_id"]), include_overlapping=True)
        assert r.blocked and any("Texte fonction" in p for x in r.with_problems for p in x.problems)

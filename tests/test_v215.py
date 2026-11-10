"""V2.15 : séquences modèles (P1–P3, G1–G6, S1–S2) et textes fonction / secteur chargés au
premier lancement ; suppression des séquences de test d'Omar si elles n'ont jamais servi."""
from sqlalchemy import func, select

from app import render, starter_data
from app import sequences_service as ss
from app.db import get_session
from app.models import Campaign, ContentBlock, Contact, Enrollment, Mailbox, Sequence
from app.seed import run_seed


def _setup(s):
    run_seed(s)  # crée « Prospection PME – 3 étapes » et les 10 textes « À RÉDIGER »
    mb = Mailbox(display_name="Omar", email="o@oddo.ma", signature="Omar Douiri\nODDO Assurances")
    s.add(mb)
    s.flush()
    return mb


def test_starter_sequences_fresh_install(db):
    data = starter_data.load_sequences()
    with get_session() as s:
        _setup(s)
        r = starter_data.apply_sequences(s)
        s.commit()
        assert r["sequences_created"] == len(data["sequences"]) == 25  # V3 : + 10 cotations par branche ; V3.5.1 : + 4
        assert r["sequences_removed"] == 1 and r["blocks_filled"] == 12  # V3.4 : + 2 textes génériques
        names = set(s.scalars(select(Sequence.name)))
        assert "Prospection PME – 3 étapes" not in names
        cats = {q.name[:2]: q.category for q in s.scalars(select(Sequence))}
        assert cats["P1"] == "prospection" and cats["G2"] == "gestion" and cats["S1"] == "souscription"
        assert not any(render.TODO_MARKER in b.body for b in s.scalars(select(ContentBlock)))
        # deuxième passage : rien ne bouge
        assert starter_data.apply_sequences(s).get("skipped")
        assert s.scalar(select(func.count(Sequence.id))) == 25


def test_starter_sequences_render(db):
    with get_session() as s:
        _setup(s)
        starter_data.apply_sequences(s)
        c = Contact(email="k@3s.ma", first_name="Khaoula", last_name="R", company="3S Morocco",
                    sequence_code="FIN-IND")
        s.add(c)
        s.flush()
        for seq in s.scalars(select(Sequence)):
            steps = ss.preview(s, seq, c)
            assert len(steps) >= 2
            assert not steps[0].same_thread and all(p.same_thread for p in steps[1:])
            assert all(p.subject for p in steps)
            for p in steps:
                assert "{{" not in p.body and "Omar Douiri" in p.body
                assert not p.warnings
            if seq.name.startswith("P"):
                assert all(not p.problems for p in steps), (seq.name, [p.problems for p in steps])
            else:  # gestion / souscription : champs à compléter dans le 1er email
                assert any(x.startswith("À compléter") for x in steps[0].problems)
        p1 = next(q for q in s.scalars(select(Sequence)) if q.name.startswith("P1"))
        body = ss.preview(s, p1, c)[0].body
        assert "responsable des finances de 3S Morocco" in body and "bris de machine" in body


def test_starter_keeps_edited_and_used(db):
    with get_session() as s:
        mb = _setup(s)
        fin = s.scalars(select(ContentBlock).where(ContentBlock.key == "FIN")).one()
        fin.body = "Mon texte à moi."
        pme = Sequence(name="PME")
        dele = Sequence(name="Délégation")
        mine = Sequence(name="G1 · Demande d'avenant")  # même nom qu'un modèle : on n'en crée pas un 2e
        s.add_all([pme, dele, mine])
        s.flush()
        seed_seq = s.scalars(select(Sequence).where(Sequence.name == "Prospection PME – 3 étapes")).one()
        s.add(Campaign(name="Brouillon", mailbox_id=mb.id, sequence_id=seed_seq.id, status="draft"))
        used = Campaign(name="Lancée", mailbox_id=mb.id, sequence_id=pme.id, status="active")
        s.add(used)
        s.flush()
        c = Contact(email="x@y.ma")
        s.add(c)
        s.flush()
        s.add(Enrollment(campaign_id=used.id, contact_id=c.id))
        s.commit()
        r = starter_data.apply_sequences(s)
        s.commit()
        assert r["sequences_removed"] == 2 and r["sequences_kept"] == ["PME"]
        assert r["sequences_created"] == 24 and r["blocks_filled"] == 11
        assert s.scalars(select(ContentBlock).where(ContentBlock.key == "FIN")).one().body == "Mon texte à moi."
        names = list(s.scalars(select(Sequence.name)))
        assert names.count("G1 · Demande d'avenant") == 1 and "PME" in names and "Délégation" not in names
        assert s.scalar(select(func.count(Campaign.id))) == 1

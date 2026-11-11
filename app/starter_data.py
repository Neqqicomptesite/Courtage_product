"""Données de départ (V2.12) : les compagnies d'assurance partenaires d'ODDO, avec leur logo et
leurs interlocuteurs (service, niveau, poste). Fournies par Omar (Liste_contacts.xlsx, 04/11/2026)
pour que chaque collègue retrouve tout dès la première ouverture.

Règles :
- appliqué une seule fois par version de la liste (réglage « starter_insurers_version ») ;
- on n'efface ni ne remplace rien : une entreprise déjà présente (même nom, ou un alias comme
  « Sanlam » pour « Sanlam Allianz ») est complétée (type Assureur, domaine, logo s'il manque) ;
- un contact déjà présent (même email) passe Assureur et reçoit service / niveau / poste
  seulement s'ils sont vides ; ses notes et son historique ne bougent pas ;
- les contacts créés sont marqués « Assureurs ODDO (liste de départ) » comme source.
"""
from __future__ import annotations

import json
import logging
import shutil
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import companies_service as co
from app import contacts_service as cs
from app import render, settings_store
from app.models import Campaign, Company, ContentBlock, Contact, Enrollment, EventLog, Sequence, Step, StepVariant
from app.paths import data_dir

log = logging.getLogger(__name__)
HERE = Path(__file__).parent / "starter"
SOURCE = "Assureurs ODDO (liste de départ)"


def load() -> dict:
    return json.loads((HERE / "assureurs.json").read_text(encoding="utf-8"))


def _find_company(s: Session, names: list[str]) -> Company | None:
    for n in names:
        c = co.find(s, n)
        if c:
            return c
    return None


def apply(s: Session, force: bool = False) -> dict:
    data = load()
    version = int(data["version"])
    if not force and int(settings_store.get(s, "starter_insurers_version") or 0) >= version:
        return {"skipped": True}
    logos = data_dir() / "logos"
    logos.mkdir(parents=True, exist_ok=True)
    report = {"companies_created": 0, "companies_updated": 0, "contacts_created": 0, "contacts_updated": 0}
    for spec in data["companies"]:
        comp = _find_company(s, [spec["name"], *spec.get("aliases", [])])
        if comp is None:
            comp, _ = co.get_or_create(s, spec["name"], "insurer", spec.get("domain"))
            report["companies_created"] += 1
        else:
            if comp.name != spec["name"] and co.find(s, spec["name"]) in (None, comp):
                co.rename(s, comp, spec["name"])
            report["companies_updated"] += 1
        if comp.kind != "insurer":
            co.set_kind(s, comp, "insurer")
        comp.domain = comp.domain or spec.get("domain")
        if not comp.logo and spec.get("logo") and (HERE / "logos" / spec["logo"]).is_file():
            name = f"{comp.id}-depart-{spec['logo']}"
            shutil.copyfile(HERE / "logos" / spec["logo"], logos / name)
            comp.logo = name
        s.flush()
        for p in spec["people"]:
            email = p["email"].strip().lower()
            c = s.scalars(select(Contact).where(Contact.email == email)).first()
            if c is None:
                c, _ = cs.create_contact(s, {"email": email, "first_name": p["first_name"], "last_name": p["last_name"],
                                             "job_title": p["job_title"], "company": comp.name, "kind": "insurer"}, SOURCE)
                report["contacts_created"] += 1
            else:
                report["contacts_updated"] += 1
                if not c.company_id:
                    c.company = comp.name
                    co.link(s, c, kind_explicit=True)
                c.job_title = c.job_title or p["job_title"]
            if c.kind != "insurer":
                co.set_contact_kind(s, c, "insurer")
            c.department = c.department or p["department"]
            c.seniority = c.seniority or p["seniority"]
    settings_store.set_(s, "starter_insurers_version", version)
    s.add(EventLog(level="info", entity="company",
                   text=(f"Assureurs de départ : {report['companies_created']} compagnie(s) ajoutée(s), "
                         f"{report['companies_updated']} complétée(s) ; {report['contacts_created']} contact(s) ajouté(s), "
                         f"{report['contacts_updated']} complété(s)")))
    return report


# ------------------------------------------------------------- V2.15 : séquences et textes

def load_sequences() -> dict:
    return json.loads((HERE / "sequences.json").read_text(encoding="utf-8"))


def _removable(s: Session, seq: Sequence) -> list[Campaign] | None:
    """Une séquence de test ne part que si ses campagnes sont des brouillons vides
    (aucune personne inscrite) ; sinon on la garde, son historique compte."""
    camps = list(s.scalars(select(Campaign).where(Campaign.sequence_id == seq.id)))
    for c in camps:
        if c.status != "draft" or s.scalars(select(Enrollment.id).where(Enrollment.campaign_id == c.id)).first():
            return None
    return camps


def apply_sequences(s: Session, force: bool = False) -> dict:
    """Séquences modèles (P1–P3, G1–G6, S1–S2) et textes par fonction / secteur.

    Règles : appliqué une fois par version (« starter_sequences_version ») ; un texte n'est
    rempli que s'il est absent ou encore « À RÉDIGER » (un texte réécrit n'est jamais remplacé) ;
    une séquence n'est ajoutée que si aucune séquence ne porte déjà ce nom ; les séquences de
    test listées ne sont supprimées que si aucune campagne lancée ne les utilise."""
    data = load_sequences()
    version = int(data["version"])
    if not force and int(settings_store.get(s, "starter_sequences_version") or 0) >= version:
        return {"skipped": True}
    report = {"blocks_filled": 0, "sequences_created": 0, "sequences_removed": 0, "sequences_kept": []}

    for name in data.get("remove_sequences", []):
        for seq in list(s.scalars(select(Sequence).where(Sequence.name == name))):
            camps = _removable(s, seq)
            if camps is None:
                report["sequences_kept"].append(name)
                continue
            for c in camps:
                s.delete(c)
            s.flush()
            s.delete(seq)
            s.flush()
            report["sequences_removed"] += 1

    for kind, field in (("target", "target_blocks"), ("sector", "sector_blocks")):
        for key, body in data[field].items():
            b = s.scalars(select(ContentBlock).where(ContentBlock.kind == kind, ContentBlock.key == key)).first()
            if b is None:
                s.add(ContentBlock(kind=kind, key=key, body=body))
            elif render.TODO_MARKER in (b.body or "") or not (b.body or "").strip():
                b.body = body
            else:
                continue
            report["blocks_filled"] += 1
    s.flush()

    # V3 : textes de départ corrigés après coup, remplacés seulement s'ils n'ont pas été retouchés
    report["texts_updated"] = 0
    for fix in data.get("replace_texts", []):
        for seq in s.scalars(select(Sequence).where(Sequence.name == fix["name"], Sequence.owner_id.is_(None))
                             .execution_options(oddo_all=True)):
            st = s.scalars(select(Step).where(Step.sequence_id == seq.id, Step.position == fix["position"])).first()
            if st is not None and st.body_template == fix["old"]:
                st.body_template = fix["new"]
                report["texts_updated"] += 1
    s.flush()

    existing = {n for n in s.scalars(select(Sequence.name))}
    for spec in data["sequences"]:
        if spec["name"] in existing:
            continue
        seq = Sequence(name=spec["name"], category=spec["category"], branch=spec.get("branch"))
        s.add(seq)
        s.flush()
        for pos, stp in enumerate(spec["steps"], start=1):
            st = Step(sequence_id=seq.id, position=pos, delay_days=int(stp["delay_days"]),
                      business_days=bool(stp.get("business_days", True)),
                      same_thread=bool(stp.get("same_thread", True)) if pos > 1 else False,
                      body_template=stp["body"])
            s.add(st)
            s.flush()
            for label, subj in zip("AB", stp.get("subjects", [])):
                s.add(StepVariant(step_id=st.id, label=label, subject_template=subj))
        report["sequences_created"] += 1
    settings_store.set_(s, "starter_sequences_version", version)
    s.add(EventLog(level="info", entity="sequence",
                   text=(f"Séquences de départ : {report['sequences_created']} ajoutée(s), "
                         f"{report['sequences_removed']} séquence(s) de test supprimée(s) ; "
                         f"{report['blocks_filled']} texte(s) fonction / secteur rempli(s)"
                         + (f" ; gardées car utilisées : {', '.join(report['sequences_kept'])}"
                            if report["sequences_kept"] else ""))))
    return report


def _cleanup_v352(s: Session) -> dict:
    """Une seule fois : transferts et messages de collègues rangés à tort dans les réponses (V3.5.2)."""
    if settings_store.get(s, "cleanup_v352_done"):
        return {"skipped": True}
    from app import imap_sync
    n = imap_sync.hide_internal_and_forwards(s)
    settings_store.set_(s, "cleanup_v352_done", True)
    return {"retires": n}


def apply_at_startup(s: Session) -> None:
    """Jamais bloquant : une erreur est notée dans le journal et l'application démarre quand même."""
    for label, fn in (("assureurs", apply), ("séquences", apply_sequences), ("nettoyage des réponses", _cleanup_v352)):
        try:
            with s.begin_nested():
                r = fn(s)
            if not r.get("skipped"):
                log.info("Données de départ (%s) chargées : %s", label, r)
        except Exception:  # noqa: BLE001
            log.exception("Chargement des données de départ (%s) impossible", label)

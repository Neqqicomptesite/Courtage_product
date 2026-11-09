"""Séquences, étapes, blocs, et aperçu d'un email pour un contact (§6.3, §6.4)."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import render, settings_store
from app.mailbox_service import get_primary
from app.models import Campaign, ContentBlock, Contact, Sequence, Step, StepVariant
from app.scheduling import SendWindow, planned_dates
from app.timeutil import utcnow

DEFAULT_STEPS = [(0, False), (3, True), (4, True)]  # J0, J+3, J+7 ouvrés (délai depuis l'étape précédente)
MAX_LINKS = 1  # §8 : au plus un lien par email


def steps_of(session: Session, seq: Sequence) -> list[Step]:
    return list(session.scalars(select(Step).where(Step.sequence_id == seq.id).order_by(Step.position)))


def variants_of(session: Session, step: Step) -> dict[str, StepVariant]:
    return {v.label: v for v in session.scalars(select(StepVariant).where(StepVariant.step_id == step.id))}


def blocks(session: Session) -> tuple[dict[str, str], dict[str, str]]:
    target, sector = {}, {}
    for b in session.scalars(select(ContentBlock)):
        (target if b.kind == "target" else sector)[b.key] = b.body
    return target, sector


def steps_for(session: Session, seq: Sequence, enr) -> list[Step]:
    """V2.24 : les étapes que CETTE inscription doit envoyer (les N premières si on a choisi
    « 1er email seulement » ou « 1er email + relance 1 »)."""
    steps = steps_of(session, seq)
    n = getattr(enr, "max_steps", None)
    return steps[:n] if n else steps


def create_sequence(session: Session, name: str, n_steps: int = 3) -> Sequence:
    """n_steps = 1 (V2.23) : un seul email, un modèle à réutiliser depuis « Nouveau message » → Modèles."""
    from app.current import user_id
    seq = Sequence(name=name, owner_id=user_id())  # V3 : modèle personnel de celui qui le crée
    session.add(seq)
    session.flush()
    for pos, (delay, same_thread) in enumerate(DEFAULT_STEPS[:max(1, n_steps)], start=1):
        st = Step(sequence_id=seq.id, position=pos, delay_days=delay, business_days=True,
                  same_thread=same_thread, body_template="")
        session.add(st)
        session.flush()
        if pos == 1:
            session.add(StepVariant(step_id=st.id, label="A", subject_template=""))
    return seq


def campaigns_using(session: Session, seq: Sequence) -> int:
    """Campagnes qui utilisent ce modèle, celles des collègues comprises (V3.3.3) : un modèle
    commun utilisé par Hamza ne doit pas pouvoir être supprimé ou décalé par quelqu'un d'autre."""
    return session.scalar(select(func.count(Campaign.id)).where(Campaign.sequence_id == seq.id)
                          .execution_options(oddo_all=True)) or 0


def renumber(session: Session, seq: Sequence) -> None:
    """Après une suppression, positions 1, 2, 3… sans trou. Deux passes car (sequence_id,
    position) est unique : on passe d'abord par des positions négatives temporaires."""
    steps = steps_of(session, seq)
    for i, st in enumerate(steps, start=1):
        st.position = -i
    session.flush()
    for st in steps:
        st.position = -st.position
    session.flush()


# ------------------------------------------------------------------- aperçu

@dataclass
class StepPreview:
    position: int
    subject: str
    body: str
    planned_at: datetime | None
    same_thread: bool
    problems: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def preview_variant(contact: Contact, labels: list[str]) -> str:
    """Variante affichée dans l'aperçu (le vrai tirage A/B se fait à l'inscription, en M4).
    Calculée à partir de l'email pour rester la même d'un affichage à l'autre."""
    if not labels:
        return "A"
    h = int(hashlib.sha256(contact.email.encode()).hexdigest(), 16)
    return sorted(labels)[h % len(labels)]


def build_context(session: Session, contact: Contact, code: str | None = None) -> render.RenderContext:
    mb = get_primary(session)
    target, sector = blocks(session)
    return render.RenderContext(contact=contact, signature=mb.signature if mb else "",
                                target_blocks=target, sector_blocks=sector, code=code)


def resolve_code(block_map: dict | None, contact_code: str | None, salt: int,
                 counters: dict | None = None) -> str | None:
    """V3.4 : textes envoyés à un contact dans une campagne. La campagne peut remplacer la
    fonction et/ou le secteur de la fiche (« FIN » → « FIN2 »), ou partager entre plusieurs
    variantes (liste : à tour de rôle avec `counters`, sinon d'après `salt`). None = code de la fiche."""
    if not block_map:
        return None
    t, _, sct = (contact_code or "").upper().partition("-")

    def pick(kind: str, key: str) -> str:
        v = (block_map.get(kind) or {}).get(key or render.GENERIC)
        if isinstance(v, list):
            v = [x for x in v if x]
            if not v:
                return key
            if counters is not None:
                i = counters.get((kind, key), 0)
                counters[(kind, key)] = i + 1
                return v[i % len(v)]
            return v[salt % len(v)]
        return v or key
    code = f"{pick('target', t)}-{pick('sector', sct)}"
    return None if code == (contact_code or "").upper() or code == "-" else code


def assign_codes(session: Session, camp) -> int:
    """Fixe les textes des inscriptions dont le 1er email n'est pas encore parti, d'après les
    textes de la campagne ; un partage A/B alterne les personnes (moitié / moitié)."""
    from app.models import Enrollment, Message
    sent = select(Message.enrollment_id).where(Message.direction == "out", Message.sent_at.is_not(None))
    rows = session.execute(select(Enrollment, Contact).join(Contact, Contact.id == Enrollment.contact_id)
                           .where(Enrollment.campaign_id == camp.id, Enrollment.id.not_in(sent))
                           .order_by(Enrollment.id)).all()
    counters: dict = {}
    for enr, contact in rows:
        enr.block_code = resolve_code(camp.block_map, contact.sequence_code, enr.id, counters)
    return len(rows)


def enrollment_code(enr, camp, contact: Contact) -> str | None:
    """Le code fixé à l'inscription (1er email), sinon celui que donne la campagne."""
    if getattr(enr, "block_code", None):
        return enr.block_code
    return resolve_code(getattr(camp, "block_map", None), contact.sequence_code, enr.id or 0)


@dataclass
class ComposedStep:
    subject: str
    body: str
    problems: list[str]
    warnings: list[str]


def compose_step(ctx: render.RenderContext, st: Step, variants: dict[str, StepVariant],
                 variant: str | None, first_subject: str, unsubscribe: str,
                 override: dict | None = None) -> ComposedStep:
    """Objet + corps d'UNE étape pour UN contact. Utilisé à l'identique par l'aperçu
    et par le moteur d'envoi : ce que montre l'aperçu est exactement ce qui part.
    `override` (V2.9) : objet et/ou texte réécrits pour ce contact seulement ; la signature
    et la ligne STOP restent ajoutées comme d'habitude."""
    problems: list[str] = []
    warnings: list[str] = []
    override = override or {}
    body_template = override.get("body") or st.body_template
    if (st.position == 1 or not st.same_thread) and (override.get("subject") or "").strip():
        r = render.render(override["subject"], ctx)
        subject = r.text
        problems += [f"Objet : {p}" for p in r.problems]
    elif st.position == 1 or not st.same_thread:
        label = variant if (variant and variant in variants) else preview_variant(ctx.contact, list(variants))
        v = variants.get(label)
        if v is None or not v.subject_template.strip():
            problems.append("Objet manquant")
            subject = ""
        else:
            r = render.render(v.subject_template, ctx)
            subject = r.text
            problems += [f"Objet : {p}" for p in r.problems]
    else:
        subject = render.subject_for_reply(first_subject)

    if not body_template.strip():
        problems.append("Corps du message vide")
    if render.TODO_MARKER in body_template:
        problems.append(f"Le texte de l'étape contient encore « {render.TODO_MARKER} »")
    if render.TODO_MARKER in subject:
        problems.append(f"L'objet contient encore « {render.TODO_MARKER} »")
    body_r = render.render(body_template, ctx)
    problems += body_r.problems
    holes = render.placeholders(subject) + render.placeholders(body_r.text)
    if holes:  # V2.14 : « [N° de police] » non remplacé
        problems.append("À compléter : " + ", ".join(f"[{h}]" for h in dict.fromkeys(holes)))
    body = render.full_body(body_r.text, body_template, ctx.signature, unsubscribe)
    n_links = render.count_links(body)
    if n_links > MAX_LINKS:
        warnings.append(f"{n_links} liens dans l'email : au-delà d'un lien, "
                        "le risque de passer en spam augmente (§8)")
    return ComposedStep(subject, body, list(dict.fromkeys(problems)), warnings)


def _own_subject(st: Step) -> bool:
    return st.position == 1 or not st.same_thread


def template_holes(session: Session, seq: Sequence, max_steps: int | None = None) -> list[str]:
    """V2.23 : les [champs] des emails de la séquence (objets et textes), dans l'ordre.
    Envoyée à plusieurs personnes (3 compagnies pour une cotation), on les remplit une fois.
    V2.24 : seulement ceux des emails qui partiront (max_steps)."""
    out: list[str] = []
    for st in steps_of(session, seq)[:max_steps or None]:
        if _own_subject(st):
            for v in sorted(variants_of(session, st).values(), key=lambda v: v.label):
                out += render.placeholders(v.subject_template)
        out += render.placeholders(st.body_template)
    return list(dict.fromkeys(out))


def fill_overrides(session: Session, seq: Sequence, fills: dict[str, str], attachment_ids: list[int] | None = None) -> dict:
    """Les emails de la séquence avec les [champs] remplacés, pour TOUTES les personnes choisies.
    Les variables de la personne ({{ prenom }}…) restent : chacun reçoit son email. Seules les
    étapes réellement modifiées sont réécrites ; un objet A/B réécrit garde la variante A."""
    fills = {k.strip(): v.strip() for k, v in (fills or {}).items() if k.strip() and (v or "").strip()}
    def put(t: str) -> str:
        return render.PLACEHOLDER_RE.sub(lambda m: fills.get(m.group(1).strip(), m.group(0)), t or "")
    out: dict = {}
    for st in steps_of(session, seq):
        item = {}
        body = put(st.body_template)
        if body != st.body_template:
            item["body"] = body
        if _own_subject(st):
            vs = sorted(variants_of(session, st).values(), key=lambda v: v.label)
            if vs and any(put(v.subject_template) != v.subject_template for v in vs):
                item["subject"] = put(vs[0].subject_template)
        if st.position == 1 and attachment_ids:
            item["attachment_ids"] = list(attachment_ids)
        if item:
            out[str(st.position)] = item
    return out


def is_prospection(seq: Sequence | None) -> bool:
    return seq is None or (seq.category or "prospection") == "prospection"


def unsubscribe_for(session: Session, seq: Sequence | None) -> str:
    """Ligne STOP : seulement en prospection (V2.8), et seulement si Omar l'a activée dans
    Réglages (V2.12 : facultative, désactivée par défaut)."""
    if not is_prospection(seq) or not settings_store.get(session, "unsubscribe_enabled"):
        return ""
    return settings_store.get(session, "unsubscribe_line")


def preview(session: Session, seq: Sequence, contact: Contact, variant: str | None = None,
            start_utc: datetime | None = None, overrides: dict | None = None) -> list[StepPreview]:
    ctx = build_context(session, contact)
    unsubscribe = unsubscribe_for(session, seq)
    steps = steps_of(session, seq)
    dates = planned_dates(SendWindow.from_settings(session), start_utc or utcnow(), steps) if steps else []
    out: list[StepPreview] = []
    first_subject = ""
    for st, when in zip(steps, dates):
        c = compose_step(ctx, st, variants_of(session, st), variant, first_subject, unsubscribe,
                         (overrides or {}).get(str(st.position)))
        if st.position == 1:
            first_subject = c.subject
        out.append(StepPreview(st.position, c.subject, c.body, when, st.same_thread, c.problems, c.warnings))
    return out


def problems_for_contact(session: Session, seq: Sequence, contact: Contact, overrides: dict | None = None,
                         max_steps: int | None = None) -> list[str]:
    """Tous les problèmes d'un contact, pour TOUTES les variantes d'objet (A et B) :
    le tirage A/B n'a pas encore eu lieu au moment de vérifier.
    V2.24 : une relance qui ne partira pas (max_steps) ne bloque pas l'envoi."""
    first = steps_of(session, seq)[:1]
    labels = sorted(variants_of(session, first[0])) if first else []
    found: list[str] = []
    for label in labels or [None]:
        for p in preview(session, seq, contact, label, overrides=overrides):
            if max_steps and p.position > max_steps:
                continue
            found += [f"Étape {p.position} : {x}" for x in p.problems]
    return list(dict.fromkeys(found))

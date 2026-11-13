"""Campagnes : sélection des contacts, contrôles avant activation, estimation, inscription (§6.5)."""
from __future__ import annotations

import random
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from sqlalchemy import func, or_, select, update
from sqlalchemy.orm import Session

from app import contacts_service as cs
from app import engine, settings_store, suppression
from app import sequences_service as ss
from app.ab_testing import assign_variants
from app.companies_service import KIND_LABELS
from app.models import AppUser, Campaign, Contact, Enrollment, EventLog, Mailbox, Message, Sequence
from app.scheduling import SendWindow
from app.timeutil import fmt_local, to_local, utcnow


FILTER_KEYS = ("target_segment", "sector_family", "sequence_code", "wave", "reliability", "kind", "no_reply_of", "list_id",
               "contact_ids")
REPROSPECT_DAYS = 90  # V3.5 : délai avant de reprospecter quelqu'un (réglage du cabinet « reprospect_days »)
RELIABILITY_WARN_RATIO = 0.30  # §8
STATUS_LABELS = {"draft": "Brouillon", "active": "Active", "paused": "En pause", "finished": "Terminée"}
ENROLLMENT_LABELS = {
    "scheduled": "Programmé", "sending": "Envoi en cours", "waiting": "En attente de relance",
    "replied": "A répondu", "bounced": "Rebond", "unsubscribed": "Désinscrit", "stopped": "Arrêté",
    "completed": "Terminé sans réponse", "error": "Erreur", "needs_review": "À vérifier",
}


def filters_from_form(form) -> dict:
    return {k: (form.get(k) or "").strip() for k in FILTER_KEYS if (form.get(k) or "").strip()}


def parse_ids(value) -> list[int] | None:
    """« 3,8,12 » -> [3, 8, 12] ; vide -> None (pas de sélection à la main)."""
    if not value:
        return None
    return [int(x) for x in str(value).split(",") if x.strip().isdigit()]


def matching_contacts(s: Session, filters: dict) -> list[Contact]:
    f = cs.ContactFilters(**{k: filters.get(k, "") for k in FILTER_KEYS if k != "contact_ids"})
    q = cs.filtered_query(f)
    ids = parse_ids(filters.get("contact_ids"))  # V2.10 : personnes cochées une à une
    if ids is not None:
        q = q.where(Contact.id.in_(ids))
    return list(s.scalars(q))


# --------------------------------------------------------------- éligibilité

@dataclass
class Candidate:
    contact: Contact
    excluded: str | None = None                      # raison d'exclusion automatique
    other_campaigns: list[str] = field(default_factory=list)  # déjà en cours ailleurs (forçable)
    recent: str | None = None                        # V3.5 : déjà prospecté récemment (forçable)
    problems: list[str] = field(default_factory=list)          # variables non résolues : bloquant
    doubtful: str | None = None                      # V3.11.2 : email douteux (À vérifier, Moyenne…), à exclure au choix


def reprospect_days(s: Session) -> int:
    try:
        return max(0, int(settings_store.get(s, "reprospect_days") or REPROSPECT_DAYS))
    except (TypeError, ValueError):
        return REPROSPECT_DAYS


def _colleagues(s: Session) -> dict[int, str]:
    """Boîte d'envoi -> prénom ou nom de l'employé (pour dire « chez Karim »)."""
    rows = s.execute(select(Mailbox.id, AppUser.full_name, AppUser.email).join(AppUser, AppUser.id == Mailbox.user_id)
                     .execution_options(oddo_all=True))
    return {mb: (name or email or "un collègue").split()[0] for mb, name, email in rows}


def busy_elsewhere(s: Session, camp: Campaign, contact_ids=None) -> dict[int, list[str]]:
    """Contacts en cours dans une AUTRE campagne. Campagne de groupe : la sienne ou celle d'un
    collègue (V3.5 : avant, seulement les siennes ; le filtre par employé cachait les autres).
    Envoi à l'unité : seulement les siennes, comme avant (V3.3.3, pas de réservation : un collègue
    peut toujours écrire à une personne choisie, même si un autre la suit)."""
    who = _colleagues(s)
    stmt = (select(Enrollment.contact_id, Campaign.name, Campaign.mailbox_id)
            .join(Campaign, Campaign.id == Enrollment.campaign_id)
            .where(Campaign.status.in_(("active", "paused")), Campaign.id != camp.id,
                   Enrollment.status.in_(engine.OPEN_STATUSES)))
    if not camp.direct:
        stmt = stmt.execution_options(oddo_all=True)
    if contact_ids is not None:
        stmt = stmt.where(Enrollment.contact_id.in_(contact_ids))
    busy: dict[int, list[str]] = {}
    for cid, name, mb in s.execute(stmt):
        # le nom d'une campagne d'un collègue reste privé (cloisonnement V3) : on dit seulement chez qui
        busy.setdefault(cid, []).append(name if mb == camp.mailbox_id else f"une campagne de {who.get(mb, 'un collègue')}")
    return busy


def recently_prospected(s: Session, camp: Campaign, now: datetime) -> dict[int, str]:
    """V3.5 : contacts qui ont reçu un email de séquence (réel, pas un essai) depuis moins de
    `reprospect_days` jours, par n'importe qui dans l'équipe, hors de cette campagne. Ceux qui
    ont répondu sont déjà écartés par leur statut : il reste ceux qui n'ont pas répondu."""
    days = reprospect_days(s)
    if not days:
        return {}
    own = select(Enrollment.id).where(Enrollment.campaign_id == camp.id).execution_options(oddo_all=True)
    rows = s.execute(select(Message.contact_id, func.max(Message.sent_at), func.min(Message.mailbox_id))
                     .where(Message.direction == "out", Message.step_position.is_not(None),
                            Message.sent_at >= now - timedelta(days=days), Message.test_mode.is_(False),
                            Message.contact_id.is_not(None),
                            or_(Message.enrollment_id.is_(None), Message.enrollment_id.not_in(own)))
                     .group_by(Message.contact_id).execution_options(oddo_all=True))
    who = _colleagues(s)
    out = {}
    for cid, last, mb in rows:
        by = "" if mb == camp.mailbox_id else f" (par {who.get(mb, 'un collègue')})"
        out[cid] = (f"Dernier email le {to_local(last):%d/%m/%Y}{by} : relançable à partir du "
                    f"{to_local(last + timedelta(days=days)):%d/%m/%Y}")
    return out


def no_reply_summary(s: Session, camp: Campaign) -> dict:
    """V3.5 : les contacts allés au bout de la campagne sans répondre (et toujours joignables),
    à relancer plus tard avec une autre séquence : combien, et à partir de quand c'est permis."""
    ids = select(Enrollment.id).join(Contact, Contact.id == Enrollment.contact_id).where(
        Enrollment.campaign_id == camp.id, Enrollment.status == "completed", Contact.global_status == "active")
    n = s.scalar(select(func.count()).select_from(ids.subquery())) or 0
    last = s.scalar(select(func.max(Message.sent_at)).where(Message.enrollment_id.in_(ids),
                                                             Message.direction == "out")) if n else None
    days = reprospect_days(s)
    return {"count": n, "days": days, "last_sent": last.isoformat() if last else None,
            "relaunch_from": (last + timedelta(days=days)).isoformat() if last else None}


def candidates(s: Session, camp: Campaign, check_render: bool = True, now: datetime | None = None) -> list[Candidate]:
    seq = s.get(Sequence, camp.sequence_id)
    supp = suppression.suppressed_keys(s)
    already = set(s.scalars(select(Enrollment.contact_id).where(Enrollment.campaign_id == camp.id)))
    busy = busy_elsewhere(s, camp)
    prospection = ss.is_prospection(seq) and not camp.direct
    recent = recently_prospected(s, camp, now or utcnow()) if prospection else {}

    # V3.11.2 : déjà un rebond temporaire (boîte pleine, serveur refusé…) : adresse à surveiller
    doubtful = {cid: "a déjà rebondi" for cid in s.scalars(
        select(Message.contact_id).where(Message.direction == "in", Message.kind == "bounce_soft",
                                         Message.contact_id.is_not(None)).execution_options(oddo_all=True))}
    out = []
    for c in matching_contacts(s, camp.filters or {}):
        cand = Candidate(c)
        if c.id in already:
            cand.excluded = "Déjà inscrit dans cette campagne"
        elif not status_allows(c, ss.is_prospection(seq), camp.direct):
            cand.excluded = f"Statut : {cs.STATUS_LABELS[c.global_status]}"
        elif c.kind != "prospect" and ss.is_prospection(seq):  # V2.8 : gestion/souscription -> tous types
            cand.excluded = f"{KIND_LABELS[c.kind]} : jamais prospecté"
        elif suppression.is_suppressed(c.email, supp):
            cand.excluded = "Dans la liste d'exclusion"
        else:
            cand.doubtful = doubtful.get(c.id) or _doubtful_label(c)
            cand.other_campaigns = busy.get(c.id, [])
            if not cand.other_campaigns:
                cand.recent = recent.get(c.id)
            if check_render:
                cand.problems = ss.problems_for_contact(s, seq, c)
        out.append(cand)
    return out


# ---------------------------------------------------------------- estimation

def estimate(window: SendWindow, mb: Mailbox, daily_cap: int, start: datetime, n_contacts: int,
             steps) -> tuple[datetime | None, datetime | None]:
    """Simule le moteur (plafonds, fenêtre, délai moyen) pour estimer le premier et le
    dernier envoi. Hypothèse : personne ne répond (c'est donc une borne haute)."""
    if not n_contacts or not steps:
        return None, None
    avg_gap = timedelta(seconds=(mb.min_gap_s + mb.max_gap_s) / 2)
    first_due = window.step_due(start, steps[0])  # étape 1 : démarrage planifié, jour et heure éventuels
    queue = [(first_due, i, 0) for i in range(n_contacts)]  # (échéance, contact, index d'étape)
    per_day: Counter = Counter()
    recent: list[datetime] = []
    t = first_due
    first = last = None
    while queue:
        queue.sort()
        due, i, k = queue.pop(0)
        t = window.next_open(max(t, due))
        while True:
            day = to_local(t).date()
            recent = [x for x in recent if x > t - timedelta(hours=1)]
            if per_day[day] >= daily_cap:
                t = window.next_open(datetime.combine(day + timedelta(days=1), datetime.min.time(), tzinfo=to_local(t).tzinfo))
                continue
            if len(recent) >= mb.hourly_cap:
                t = window.next_open(recent[0] + timedelta(hours=1))
                continue
            break
        per_day[to_local(t).date()] += 1
        recent.append(t)
        first = first or t
        last = t
        if k + 1 < len(steps):
            nxt = steps[k + 1]
            queue.append((window.step_due(t, nxt), i, k + 1))
        t = t + avg_gap
    return first, last


# ---------------------------------------------------------------- démarrage (V2.5)

def start_of(camp: Campaign, now: datetime) -> datetime:
    """Démarrage planifié s'il est dans le futur, sinon maintenant."""
    return max(now, camp.start_at) if camp.start_at else now


def first_due_for(s: Session, camp: Campaign, first_step, now: datetime) -> datetime:
    """Échéance du 1er email : démarrage de la campagne, puis jour/heure de l'étape 1 s'il y en a."""
    start = start_of(camp, now)
    if first_step.weekday is None and not first_step.send_time and start == now:
        # V2.25 : la vraie date (prochaine ouverture des plages d'envoi), pas l'heure du clic :
        # le suivi affichait « vendredi 15:51 » pour un email qui partira lundi 09:00 (férié).
        return SendWindow.from_settings(s).next_open(now)
    return SendWindow.from_settings(s).step_due(start, first_step)


# ---------------------------------------------------------------- activation

DOUBTFUL = ("À vérifier", "Moyenne", "Générique")


def _doubtful_label(c: Contact) -> str | None:
    cat = cs.reliability_category(c.email_reliability)
    return f"qualité « {cat} »" if cat in DOUBTFUL else None


@dataclass
class ActivationReport:
    eligible: list[Candidate]
    excluded: list[Candidate]
    overlapping: list[Candidate]
    recent: list[Candidate]
    with_problems: list[Candidate]
    reliability_ratio: float
    link_warnings: list[str]
    first_send: datetime | None
    last_send: datetime | None
    test_mode: bool
    doubtful: list[Candidate] = field(default_factory=list)

    @property
    def blocked(self) -> bool:
        return bool(self.with_problems) or not self.eligible


def activation_report(s: Session, camp: Campaign, include_overlapping: bool, now: datetime | None = None,
                      include_recent: bool = False, include_doubtful: bool = True) -> ActivationReport:
    now = now or utcnow()
    cands = candidates(s, camp, now=now)
    excluded = [c for c in cands if c.excluded]
    overlapping = [c for c in cands if not c.excluded and c.other_campaigns]
    recent = [c for c in cands if not c.excluded and c.recent]
    eligible = [c for c in cands if not c.excluded and (include_overlapping or not c.other_campaigns)
                and (include_recent or not c.recent) and (include_doubtful or not c.doubtful)]
    doubtful = [c for c in cands if not c.excluded and c.doubtful]
    with_problems = [c for c in eligible if c.problems]
    not_good = sum(1 for c in eligible if cs.reliability_category(c.contact.email_reliability) != "Bonne")
    ratio = not_good / len(eligible) if eligible else 0.0

    seq = s.get(Sequence, camp.sequence_id)
    steps = ss.steps_of(s, seq)
    links = []
    if eligible:
        for p in ss.preview(s, seq, eligible[0].contact):
            links += [f"Étape {p.position} : {w}" for w in p.warnings]
    mb = s.get(Mailbox, camp.mailbox_id)
    first, last = estimate(SendWindow.from_settings(s), mb, engine.effective_daily_cap(s, mb, now),
                           start_of(camp, now), len(eligible), steps)
    return ActivationReport(eligible, excluded, overlapping, recent, with_problems, ratio, links, first, last,
                            bool(settings_store.get(s, "test_mode")), doubtful)


def activate(s: Session, camp: Campaign, include_overlapping: bool, now: datetime | None = None,
             rng: random.Random | None = None, include_recent: bool = False, include_doubtful: bool = True) -> int:
    """Inscrit les contacts éligibles, tire les variantes A/B et passe la campagne en « active »."""
    now = now or utcnow()
    report = activation_report(s, camp, include_overlapping, now, include_recent=include_recent,
                               include_doubtful=include_doubtful)
    if report.blocked:
        raise ValueError("Activation impossible : contacts avec problèmes ou aucun contact éligible.")
    seq = s.get(Sequence, camp.sequence_id)
    first_step = ss.steps_of(s, seq)[0]
    labels = sorted(ss.variants_of(s, first_step))
    existing = Counter(v for v in s.scalars(select(Enrollment.variant_label)
                                            .where(Enrollment.campaign_id == camp.id)) if v)
    variants = assign_variants([c.contact.id for c in report.eligible], labels, existing, rng)
    first_due = first_due_for(s, camp, first_step, now)
    for cand in report.eligible:
        s.add(Enrollment(campaign_id=camp.id, contact_id=cand.contact.id, variant_label=variants.get(cand.contact.id),
                         current_step=1, next_due_at=first_due, status="scheduled"))
    camp.status = "active"
    camp.activated_at = camp.activated_at or now
    s.flush()
    ss.assign_codes(s, camp)  # V3.4 : textes de la campagne (variantes, partage A/B équilibré)
    s.add(EventLog(level="warning" if not report.test_mode else "info", entity="campaign", entity_id=camp.id,
                   text=f"Campagne « {camp.name} » activée : {len(report.eligible)} contact(s)"
                        + (" (mode test)" if report.test_mode else " – ENVOIS RÉELS")
                        + (f", démarrage le {fmt_local(camp.start_at)}" if camp.start_at and camp.start_at > now else "")))
    return len(report.eligible)


def sample(s: Session, camp: Campaign, n: int = 3, now: datetime | None = None) -> list[dict]:
    """V3.9 : « Aperçu des emails » avant le lancement : les vrais emails de quelques contacts qui
    recevront la séquence, rendus comme le moteur le fera (nom, entreprise, texte de leur lot ou de
    la campagne, objet A/B, signature, pièces jointes, dates prévues). On choisit des contacts aussi
    différents que possible (lot, fonction, secteur) pour voir chaque variante de texte."""
    from app import attachments_service
    now = now or utcnow()
    seq = s.get(Sequence, camp.sequence_id)
    steps = ss.steps_of(s, seq) if seq else []
    if not steps:
        return []
    pool = [c for c in candidates(s, camp, check_render=False, now=now) if not c.excluded]
    pool.sort(key=lambda c: (bool(c.other_campaigns) or bool(c.recent), c.contact.id))  # ceux qui partiront d'abord
    chosen, seen = [], set()
    for c in pool:  # 1er passage : un contact par (lot, code) différent
        k = (c.contact.lot_number or 1, (c.contact.sequence_code or "").upper())
        if k not in seen:
            seen.add(k)
            chosen.append(c)
        if len(chosen) >= n:
            break
    for c in pool:
        if len(chosen) >= n:
            break
        if c not in chosen:
            chosen.append(c)
    window = SendWindow.from_settings(s)
    unsubscribe = ss.unsubscribe_for(s, seq)
    labels = sorted(ss.variants_of(s, steps[0]))
    keys = ss.block_keys(s)
    counters: dict = {}
    base_atts = {st.position: attachments_service.of_step(s, st.id) for st in steps}
    first_due = first_due_for(s, camp, steps[0], now)
    out = []
    for i, cand in enumerate(chosen):
        c = cand.contact
        code = ss.resolve_code(camp.block_map, c.sequence_code, i, counters, c.lot_number, keys)
        ctx = ss.build_context(s, c, code)
        variant = labels[i % len(labels)] if labels else None  # objets A/B : un contact sur deux, pour voir les deux
        emails, first_subject, prev = [], "", None
        for st in steps:
            when = first_due if prev is None else window.step_due(prev, st)
            prev = when
            r = ss.compose_step(ctx, st, ss.variants_of(s, st), variant, first_subject, unsubscribe)
            if st.position == 1:
                first_subject = r.subject
            emails.append({"position": st.position, "subject": r.subject, "body": r.body, "planned_at": when,
                           "same_thread": st.same_thread, "problems": r.problems, "warnings": r.warnings,
                           "attachments": [attachments_service.as_json(a) for a in base_atts.get(st.position, [])]})
        out.append({"contact": c, "variant": variant, "code": code or (c.sequence_code or None),
                    "lot": c.lot_number, "emails": emails})
    return out


def delete(s: Session, camp: Campaign) -> int:
    """Supprime une campagne, brouillon ou lancée (V3.4.3) ; renvoie le nombre d'emails déjà partis.
    Les envois prévus disparaissent. Les emails partis et les réponses restent dans la boîte mail et
    sur la fiche du contact, rattachés à la boîte d'envoi (ils comptent toujours dans le plafond du jour)."""
    enr_ids = select(Enrollment.id).where(Enrollment.campaign_id == camp.id)
    if s.scalar(select(func.count(Enrollment.id)).where(Enrollment.campaign_id == camp.id,
                                                       Enrollment.status == "sending")):
        raise ValueError("Un email de cette campagne part en ce moment : réessayez dans une minute.")
    sent = s.scalar(select(func.count(Message.id)).where(Message.enrollment_id.in_(enr_ids),
                                                         Message.direction == "out",
                                                         Message.sent_at.is_not(None))) or 0
    s.execute(update(Message).where(Message.enrollment_id.in_(enr_ids), Message.mailbox_id.is_(None))
              .values(mailbox_id=camp.mailbox_id))
    if camp.status != "draft":
        s.add(EventLog(level="info", entity="campaign", entity_id=camp.id,
                       text=f"Campagne « {camp.name} » supprimée"
                            + (f" ({sent} email(s) déjà envoyé(s) conservé(s))" if sent else "")))
    s.delete(camp)
    return sent


def has_sent(s: Session, camp: Campaign) -> bool:
    return bool(s.scalar(select(func.count(Message.id)).join(Enrollment, Enrollment.id == Message.enrollment_id)
                         .where(Enrollment.campaign_id == camp.id, Message.direction == "out")))


def set_start(s: Session, camp: Campaign, start_at: datetime | None, now: datetime | None = None) -> int:
    """Démarrage planifié (V2.5). Sur une campagne lancée, replanifie les 1ers emails pas encore
    partis ; renvoie leur nombre. Refusé une fois que des emails sont partis."""
    now = now or utcnow()
    if camp.status == "finished":
        raise ValueError("Cette campagne est terminée.")
    if start_at is not None and start_at < now - timedelta(minutes=5):
        raise ValueError("La date de démarrage est déjà passée.")
    if camp.status != "draft" and has_sent(s, camp):
        raise ValueError("Des emails sont déjà partis : le démarrage ne peut plus être déplacé.")
    camp.start_at = start_at
    seq = s.get(Sequence, camp.sequence_id)
    first_step = ss.steps_of(s, seq)[0]
    moved = 0
    for enr in s.scalars(select(Enrollment).where(Enrollment.campaign_id == camp.id, Enrollment.status == "scheduled",
                                                 Enrollment.current_step == 1)):
        enr.next_due_at = first_due_for(s, camp, first_step, now)
        moved += 1
    s.add(EventLog(level="info", entity="campaign", entity_id=camp.id,
                   text=f"Campagne « {camp.name} » : démarrage "
                        + (f"planifié le {fmt_local(start_at)}" if start_at else "dès que possible")))
    return moved


def pause(s: Session, camp: Campaign) -> None:
    camp.status = "paused"
    s.add(EventLog(level="info", entity="campaign", entity_id=camp.id, text=f"Campagne « {camp.name} » en pause"))


def resume(s: Session, camp: Campaign, now: datetime | None = None) -> None:
    """Reprise : les échéances dépassées pendant la pause repartent à la prochaine ouverture
    de la fenêtre (le moteur les enverra une par une, sans rafale)."""
    now = now or utcnow()
    opening = SendWindow.from_settings(s).next_open(now)
    for enr in s.scalars(select(Enrollment).where(Enrollment.campaign_id == camp.id,
                                                 Enrollment.status.in_(engine.DUE_STATUSES))):
        if enr.next_due_at and enr.next_due_at < opening:
            enr.next_due_at = opening
    camp.status = "active"
    s.add(EventLog(level="info", entity="campaign", entity_id=camp.id, text=f"Campagne « {camp.name} » reprise"))


def enrollment_counts(s: Session, camp: Campaign) -> dict[str, int]:
    return dict(s.execute(select(Enrollment.status, func.count(Enrollment.id))
                          .where(Enrollment.campaign_id == camp.id).group_by(Enrollment.status)).all())


# ------------------------------------------------- ajout d'un seul contact (V2.3)

class EnrollRefused(ValueError):
    def __init__(self, message: str, problems: list[str] | None = None, overlap: list[str] | None = None):
        super().__init__(message)
        self.problems, self.overlap = problems or [], overlap or []


def status_allows(contact: Contact, prospection: bool, direct: bool = False) -> bool:
    """V2.23 : « A répondu » ne protège que des campagnes de prospection de GROUPE (on ne
    reprospecte pas en masse quelqu'un qui a répondu). Envoyée à l'unité, une séquence reste
    possible : P2 après le rendez-vous obtenu grâce à P1, ou une demande de gestion à un
    gestionnaire qui a déjà répondu. Rebond, désinscription, « ne plus contacter » : jamais rien."""
    if contact.global_status == "active":
        return True
    return contact.global_status == "replied" and (direct or not prospection)


def claim_prospect(s: Session, contact: Contact) -> None:
    """V3.3.3 : pas de réservation. Tout le monde peut écrire à tout prospect, même si un
    collègue lui parle déjà. Le premier qui lui écrit est seulement noté comme « suivi par »
    (repère visible sur la fiche, modifiable par l'administrateur) ; cela ne bloque personne."""
    from app.current import user_id
    uid = user_id()
    if uid is None or contact.kind != "prospect" or contact.owner_id:
        return
    contact.owner_id = uid


def enroll_one(s: Session, camp: Campaign, contact: Contact, include_overlapping: bool = False,
               now: datetime | None = None, rng: random.Random | None = None,
               overrides: dict | None = None, max_steps: int | None = None) -> Enrollment:
    """Inscrit UN contact dans une campagne lancée, avec les mêmes contrôles qu'un lancement :
    statut, type (prospects seulement), exclusion, email complet, autre campagne en cours."""
    now = now or utcnow()
    if camp.status not in ("active", "paused"):
        raise EnrollRefused("Cette campagne n'est pas en cours : lancez-la d'abord, ou choisissez-en une autre.")
    seq = s.get(Sequence, camp.sequence_id)
    prospection = ss.is_prospection(seq)
    # V2.23 : gestion et souscription envoyées à l'unité = un envoi par dossier : la même personne
    # peut recevoir G1 pour un client, puis pour un autre. La prospection et les campagnes de
    # groupe gardent la règle « une seule fois ».
    if (prospection or not camp.direct) and s.scalar(select(func.count(Enrollment.id)).where(
            Enrollment.campaign_id == camp.id, Enrollment.contact_id == contact.id)):
        raise EnrollRefused("Cette personne a déjà reçu cette séquence (ou la reçoit en ce moment)." if camp.direct
                            else "Ce contact est déjà dans cette campagne.")
    if not status_allows(contact, prospection, camp.direct):
        raise EnrollRefused(f"Statut du contact : {cs.STATUS_LABELS[contact.global_status]}.")
    if contact.kind != "prospect" and prospection:
        raise EnrollRefused(f"{KIND_LABELS[contact.kind]} : seuls les prospects peuvent entrer dans une campagne de prospection.")
    if suppression.is_suppressed_db(s, contact.email):
        raise EnrollRefused("Adresse sur la liste d'exclusion.")
    claim_prospect(s, contact)  # V3.3.3 : note « suivi par » le premier, ne bloque personne
    overrides = clean_overrides(overrides)
    n_steps = len(ss.steps_of(s, seq))
    max_steps = max_steps if max_steps and 0 < max_steps < n_steps else None  # V2.24 ; sinon toute la séquence
    problems = ss.problems_for_contact(s, seq, contact, overrides, max_steps)
    if overrides:  # V2.14 : pièces ajoutées pour cette personne : existent et tiennent dans 10 Mo
        from app import attachments_service
        steps_by_pos = {st.position: st for st in ss.steps_of(s, seq)}
        for pos, ov in overrides.items():
            if ov.get("attachment_ids") and int(pos) in steps_by_pos:
                try:
                    attachments_service.check_total(attachments_service.of_step(s, steps_by_pos[int(pos)].id)
                                                    + attachments_service.get_many(s, ov["attachment_ids"]))
                except attachments_service.AttachmentError as exc:
                    problems.append(f"Email {pos} : {exc}")
    if problems:
        raise EnrollRefused("Un des emails serait incomplet pour ce contact.", problems=problems)
    busy = busy_elsewhere(s, camp, [contact.id]).get(contact.id, [])  # V3.5 : aussi chez les collègues
    if busy and not include_overlapping and prospection:  # V2.23 : un dossier de gestion n'en gêne pas un autre
        raise EnrollRefused("Ce contact est déjà en cours dans une autre campagne.", overlap=busy)
    first_step = ss.steps_of(s, seq)[0]
    labels = sorted(ss.variants_of(s, first_step))
    existing = Counter(v for v in s.scalars(select(Enrollment.variant_label)
                                            .where(Enrollment.campaign_id == camp.id)) if v)
    variant = assign_variants([contact.id], labels, existing, rng).get(contact.id)
    enr = Enrollment(campaign_id=camp.id, contact_id=contact.id, variant_label=variant,
                     current_step=1, next_due_at=first_due_for(s, camp, first_step, now), status="scheduled",
                     overrides=overrides, max_steps=max_steps)
    s.add(enr)
    s.flush()
    part = "" if not max_steps else " (1er email seulement)" if max_steps == 1 else f" ({max_steps} premiers emails)"
    cs.log(s, contact, (f"Séquence « {seq.name} » envoyée" if camp.direct else f"Ajouté à la campagne « {camp.name} »")
           + part + (" (emails personnalisés)" if overrides else ""))
    return enr


def clean_overrides(raw: dict | None) -> dict | None:
    """{"1": {"subject": "…", "body": "…"}} ; on ne garde que ce qui est rempli."""
    out = {}
    for pos, v in (raw or {}).items():
        if not isinstance(v, dict):
            continue
        item = {k: str(v[k]).replace("\r\n", "\n").strip() for k in ("subject", "body") if str(v.get(k) or "").strip()}
        ids = [int(x) for x in v.get("attachment_ids") or [] if str(x).isdigit()]
        if ids:  # V2.14 : pièces jointes ajoutées pour cette personne seulement
            item["attachment_ids"] = list(dict.fromkeys(ids))
        if item and str(pos).isdigit():
            out[str(int(pos))] = item
    return out or None


# ------------------------------------------------- envoi direct d'une séquence (V2.9)

def direct_campaign(s: Session, seq: Sequence, now: datetime | None = None) -> Campaign:
    """La campagne « à l'unité » de la séquence : créée au premier envoi, déjà lancée.
    Les envois depuis la boîte mail ou une fiche y sont regroupés (statistiques, pause)."""
    from app.mailbox_service import get_primary
    camp = s.scalars(select(Campaign).where(Campaign.direct.is_(True), Campaign.sequence_id == seq.id,
                                            Campaign.status.in_(("active", "paused")))
                     .order_by(Campaign.id.desc())).first()
    if camp:
        return camp
    mb = get_primary(s)
    if mb is None:
        raise EnrollRefused("Aucune boîte mail configurée : renseignez-la dans Réglages.")
    camp = Campaign(name=f"À l'unité – {seq.name}", mailbox_id=mb.id, sequence_id=seq.id, filters={},
                    status="active", direct=True, activated_at=now or utcnow())
    s.add(camp)
    s.flush()
    return camp


# ---------------------------------------------------------------- V3.11.3 : emails douteux d'une campagne lancée

def doubtful_open(s: Session, camp: Campaign) -> list[tuple[Enrollment, Contact, str]]:
    """Inscrits encore en cours (pas répondu, pas terminé) dont l'email est douteux : fiabilité « À vérifier »,
    « Moyenne », « Générique », ou déjà un rebond temporaire."""
    soft = set(s.scalars(select(Message.contact_id).where(Message.direction == "in", Message.kind == "bounce_soft",
                                                          Message.contact_id.is_not(None)).execution_options(oddo_all=True)))
    out = []
    for enr, c in s.execute(select(Enrollment, Contact).join(Contact, Contact.id == Enrollment.contact_id)
                            .where(Enrollment.campaign_id == camp.id, Enrollment.status.in_(engine.OPEN_STATUSES))
                            .order_by(Contact.company, Contact.email)):
        why = _doubtful_label(c) or ("a déjà rebondi" if c.id in soft else None)
        if why:
            out.append((enr, c, why))
    return out


def remove_doubtful(s: Session, camp: Campaign, enrollment_ids: list[int] | None = None) -> int:
    """Retire de la campagne les inscrits à l'email douteux (tous, ou ceux choisis). Ils ne reçoivent plus rien ;
    ils restent dans les contacts et dans leurs listes."""
    n = 0
    for enr, c, _ in doubtful_open(s, camp):
        if enrollment_ids is not None and enr.id not in enrollment_ids:
            continue
        if cs.remove_from_campaign(s, c, enr.id):
            n += 1
    if n:
        s.add(EventLog(level="info", entity="campaign", entity_id=camp.id,
                       text=f"{n} contact(s) à l'email douteux retiré(s) de la campagne « {camp.name} »"))
    return n

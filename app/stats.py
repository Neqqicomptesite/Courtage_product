"""Indicateurs (§6.8). Un seul endroit définit chaque chiffre : le tableau de bord,
la page campagne, l'export Excel et le récapitulatif utilisent tous ces fonctions.

Définitions (unité : l'INSCRIPTION, c'est-à-dire un contact dans une campagne) :
- touchés        : inscriptions ayant reçu au moins un email ;
- réponses       : inscriptions avec au moins une vraie réponse (pas une absence, pas un STOP) ;
- taux de réponse = réponses ÷ touchés (§6.8) ;
- intéressés     : réponses classées « Intéressé » par Omar ;
- rebonds / désinscriptions : statut de l'inscription ;
- absences       : inscriptions ayant reçu au moins un message d'absence ;
- terminés sans réponse : séquence allée jusqu'au bout.
Les effectifs sont toujours affichés à côté des taux : sur 8 contacts, un taux ne veut presque rien dire.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Contact, Enrollment, Message

AB_MIN_SAMPLE = 100  # §6.8 : en dessous, mention « échantillon trop petit »


def rate(num: int, den: int) -> float | None:
    return (num / den) if den else None


@dataclass
class Indicators:
    enrolled: int = 0
    reached: int = 0
    sent_by_step: dict[int, int] = field(default_factory=dict)
    replies: int = 0
    interested: int = 0
    bounced: int = 0
    unsubscribed: int = 0
    out_of_office: int = 0
    completed_no_reply: int = 0

    @property
    def sent_total(self) -> int:
        return sum(self.sent_by_step.values())

    @property
    def reply_rate(self) -> float | None:
        return rate(self.replies, self.reached)


@dataclass
class SegmentRow:
    key: str
    reached: int
    replies: int

    @property
    def rate(self) -> float | None:
        return rate(self.replies, self.reached)


def _enr_filter(campaign_id: int | None):
    return [Enrollment.campaign_id == campaign_id] if campaign_id else []


def _enrollments_with_inbound(kind_clause, campaign_id):
    return (select(Message.enrollment_id).distinct()
            .join(Enrollment, Enrollment.id == Message.enrollment_id)
            .where(Message.direction == "in", kind_clause, *_enr_filter(campaign_id)))


def _reached_ids(campaign_id):
    return (select(Message.enrollment_id).distinct().join(Enrollment, Enrollment.id == Message.enrollment_id)
            .where(Message.direction == "out", Message.sent_at.is_not(None), *_enr_filter(campaign_id)))


def indicators(s: Session, campaign_id: int | None = None) -> Indicators:
    f = _enr_filter(campaign_id)
    count = lambda q: s.scalar(select(func.count()).select_from(q.subquery())) or 0  # noqa: E731
    ind = Indicators()
    ind.enrolled = s.scalar(select(func.count(Enrollment.id)).where(*f)) or 0
    ind.reached = count(_reached_ids(campaign_id))
    ind.sent_by_step = dict(s.execute(
        select(Message.step_position, func.count(Message.id)).join(Enrollment, Enrollment.id == Message.enrollment_id)
        .where(Message.direction == "out", Message.sent_at.is_not(None), *f)
        .group_by(Message.step_position).order_by(Message.step_position)).all())
    ind.replies = count(_enrollments_with_inbound(Message.kind == "reply", campaign_id))
    ind.interested = count(_enrollments_with_inbound(Message.classification == "interested", campaign_id))
    ind.out_of_office = count(_enrollments_with_inbound(Message.kind == "auto_reply", campaign_id))
    by_status = dict(s.execute(select(Enrollment.status, func.count(Enrollment.id)).where(*f)
                               .group_by(Enrollment.status)).all())
    ind.bounced = by_status.get("bounced", 0)
    ind.unsubscribed = by_status.get("unsubscribed", 0)
    ind.completed_no_reply = by_status.get("completed", 0)
    return ind


def indicators_many(s: Session, campaign_ids: list[int]) -> dict[int, Indicators]:
    """V3 : indicateurs de plusieurs campagnes en ~8 requêtes au total (au lieu de ~9 par
    campagne). Sur le serveur, chaque requête fait l'aller-retour jusqu'à la base."""
    out = {cid: Indicators() for cid in campaign_ids}
    if not campaign_ids:
        return out
    in_ids = Enrollment.campaign_id.in_(campaign_ids)
    for cid, status, n in s.execute(select(Enrollment.campaign_id, Enrollment.status, func.count(Enrollment.id))
                                    .where(in_ids).group_by(Enrollment.campaign_id, Enrollment.status)):
        ind = out[cid]
        ind.enrolled += n
        if status == "bounced":
            ind.bounced = n
        elif status == "unsubscribed":
            ind.unsubscribed = n
        elif status == "completed":
            ind.completed_no_reply = n

    def per_campaign(ids_select) -> dict[int, int]:
        return dict(s.execute(select(Enrollment.campaign_id, func.count(Enrollment.id))
                              .where(in_ids, Enrollment.id.in_(ids_select)).group_by(Enrollment.campaign_id)).all())
    for cid, n in per_campaign(_reached_ids(None)).items():
        out[cid].reached = n
    for attr, clause in (("replies", Message.kind == "reply"), ("interested", Message.classification == "interested"),
                         ("out_of_office", Message.kind == "auto_reply")):
        for cid, n in per_campaign(_enrollments_with_inbound(clause, None)).items():
            setattr(out[cid], attr, n)
    rows = s.execute(select(Enrollment.campaign_id, Message.step_position, func.count(Message.id))
                     .join(Enrollment, Enrollment.id == Message.enrollment_id)
                     .where(Message.direction == "out", Message.sent_at.is_not(None), in_ids)
                     .group_by(Enrollment.campaign_id, Message.step_position).order_by(Message.step_position))
    for cid, pos, n in rows:
        out[cid].sent_by_step[pos] = n
    return out


def _grouped(s: Session, group_col, campaign_id: int | None, base_ids=None) -> list[SegmentRow]:
    """Touchés et réponses regroupés par une colonne (code séquence, variante A/B…)."""
    base_ids = base_ids if base_ids is not None else _reached_ids(campaign_id)
    reached = dict(s.execute(
        select(group_col, func.count(Enrollment.id)).join(Contact, Contact.id == Enrollment.contact_id)
        .where(Enrollment.id.in_(base_ids)).group_by(group_col)).all())
    replied_ids = _enrollments_with_inbound(Message.kind == "reply", campaign_id)
    replies = dict(s.execute(
        select(group_col, func.count(Enrollment.id)).join(Contact, Contact.id == Enrollment.contact_id)
        .where(Enrollment.id.in_(base_ids), Enrollment.id.in_(replied_ids)).group_by(group_col)).all())
    return [SegmentRow(k or "—", n, replies.get(k, 0)) for k, n in sorted(reached.items(), key=lambda x: (x[0] or "~"))]


def by_segment(s: Session, campaign_id: int | None = None) -> list[SegmentRow]:
    """Tableau par segment cible × secteur, c'est-à-dire par code séquence (§6.8)."""
    return _grouped(s, Contact.sequence_code, campaign_id)


def ab_test(s: Session, campaign_id: int | None = None) -> tuple[list[SegmentRow], bool]:
    """Par variante d'objet : contacts ayant reçu l'étape 1, réponses, taux.
    Renvoie aussi True si l'échantillon est trop petit pour conclure."""
    step1 = (select(Message.enrollment_id).distinct().join(Enrollment, Enrollment.id == Message.enrollment_id)
             .where(Message.direction == "out", Message.sent_at.is_not(None), Message.step_position == 1,
                    Enrollment.variant_label.is_not(None), *_enr_filter(campaign_id)))
    rows = _grouped(s, Enrollment.variant_label, campaign_id, base_ids=step1)
    too_small = not rows or any(r.reached < AB_MIN_SAMPLE for r in rows)
    return rows, too_small


def unclassified_count(s: Session) -> int:
    """Compteur du menu « Réponses » : vraies réponses et STOP pas encore classés."""
    return s.scalar(select(func.count(Message.id)).where(
        Message.direction == "in", Message.kind.in_(("reply", "unsubscribe")),
        Message.classification.is_(None))) or 0


# ------------------------------------------------- sans réponse depuis N jours ouvrés (V2.2)

STOPPING_KINDS = ("reply", "unsubscribe", "bounce_hard", "bounce_soft")


def followups(s: Session, now, window, days: int = 3) -> list[dict]:
    """Contacts actifs dont le dernier email est parti il y a au moins `days` jours OUVRÉS
    (week-ends et fériés exclus) sans réponse DEPUIS : la liste à relancer par téléphone.
    Une réponse automatique (absence) ne compte pas comme une réponse.
    V2.25 : une réponse à un échange PLUS ANCIEN n'exclut plus la personne pour toujours
    (un assureur qui a répondu à une cotation le mois dernier, puis plus rien sur la nouvelle).
    V2.25.1 : comme avant, la personne apparaît N jours ouvrés après chaque email resté sans
    réponse, même si une relance automatique est encore prévue (choix d'Omar)."""
    from app.models import Campaign
    from app.timeutil import to_local

    last = (select(Message.contact_id, func.max(Message.sent_at).label("last"))
            .where(Message.direction == "out", Message.sent_at.is_not(None))
            .group_by(Message.contact_id).subquery())
    today = to_local(now).date()
    out = []
    for c, last_sent in s.execute(select(Contact, last.c.last).join(last, last.c.contact_id == Contact.id)
                                  .where(Contact.global_status == "active")
                                  .order_by(last.c.last)):
        if s.scalar(select(Message.id).where(Message.contact_id == c.id, Message.direction == "in",
                                             Message.kind.in_(STOPPING_KINDS),
                                             Message.received_at >= last_sent).limit(1)):
            continue  # a répondu après le dernier email
        d, elapsed = to_local(last_sent).date(), 0
        while d < today:
            d = d.fromordinal(d.toordinal() + 1)
            elapsed += window.is_business_day(d)
        if elapsed < days:
            continue
        msg = s.scalars(select(Message).where(Message.contact_id == c.id, Message.direction == "out",
                                              Message.sent_at.is_not(None))
                        .order_by(Message.sent_at.desc(), Message.id.desc())).first()
        enr = s.get(Enrollment, msg.enrollment_id) if msg and msg.enrollment_id else None
        camp = s.get(Campaign, enr.campaign_id) if enr else None
        nxt = s.scalars(select(Enrollment).where(Enrollment.contact_id == c.id,
                                                 Enrollment.status.in_(("scheduled", "sending", "waiting")),
                                                 Enrollment.next_due_at.is_not(None))
                        .order_by(Enrollment.next_due_at)).first()
        out.append({"contact": c, "last_sent": last_sent, "business_days": elapsed, "next": nxt,
                    "next_campaign": s.get(Campaign, nxt.campaign_id) if nxt else None,
                    "step": msg.step_position if msg else None, "subject": msg.subject if msg else "",
                    "campaign": camp, "enrollment": enr, "message": msg})
    return out

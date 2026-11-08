"""Email récapitulatif quotidien envoyé à Omar (§6.9).

- vérifié chaque minute : part dès que l'heure configurée est passée, une fois par jour
  (si le PC était éteint à 18:00, il part à l'ouverture de l'app le même jour) ;
- uniquement s'il y a eu de l'activité ;
- ne compte pas dans les plafonds de prospection et n'est pas enregistré comme envoi de campagne ;
- toujours adressé à Omar (ou au destinataire choisi), jamais à un contact.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import APP_NAME
from app import BASE_URL, credentials, engine, settings_store
from app.db import get_session
from app.mail import compose, transport
from app.mailbox_service import as_form_values, get_primary, server_config
from app.models import Campaign, Contact, Enrollment, EventLog, Message
from app.replies_service import due_callbacks
from app.scheduling import SendWindow
from app.timeutil import TZ, to_local, utcnow

log = logging.getLogger(__name__)


@dataclass
class DigestContent:
    replies: list[tuple[Message, Contact]]
    bounces: list[tuple[Message, Contact]]
    unsubscribes: list[tuple[Message, Contact]]
    sent_today: int
    planned_tomorrow: int
    callbacks: list[tuple[Message, Contact]]

    @property
    def has_activity(self) -> bool:
        return bool(self.replies or self.bounces or self.unsubscribes or self.sent_today or self.callbacks)


def _day_bounds(day: date) -> tuple[datetime, datetime]:
    start = datetime.combine(day, time(0), tzinfo=TZ)
    return start, start + timedelta(days=1)


def collect(s: Session, now: datetime) -> DigestContent:
    today = to_local(now).date()
    start, end = _day_bounds(today)

    def inbound(kind):
        return list(s.execute(select(Message, Contact).join(Contact, Contact.id == Message.contact_id)
                              .where(Message.direction == "in", Message.kind == kind,
                                     Message.received_at >= start, Message.received_at < end)
                              .order_by(Message.received_at)))

    sent_today = s.scalar(select(func.count(Message.id)).where(
        Message.direction == "out", Message.sent_at >= start, Message.sent_at < end)) or 0
    # « prévus demain » : échéances tombant demain (estimation, les plafonds peuvent en décaler)
    t_start, t_end = _day_bounds(today + timedelta(days=1))
    planned = s.scalar(select(func.count(Enrollment.id)).join(Campaign, Campaign.id == Enrollment.campaign_id)
                       .where(Campaign.status == "active", Enrollment.status.in_(engine.DUE_STATUSES),
                              Enrollment.next_due_at < t_end)) or 0
    mb = get_primary(s)
    if mb is not None:
        planned = min(planned, engine.effective_daily_cap(s, mb, now))
    return DigestContent(inbound("reply"), inbound("bounce_hard"), inbound("unsubscribe"), sent_today, planned,
                         due_callbacks(s, today))


def render_text(c: DigestContent, now: datetime) -> tuple[str, str]:
    day = to_local(now)
    lines = [f"Récapitulatif {APP_NAME} du {day:%d/%m/%Y}", ""]
    if c.replies:
        lines.append(f"NOUVELLES RÉPONSES ({len(c.replies)})")
        for m, ct in c.replies:
            excerpt = " ".join((m.body_text or "").split())[:200]
            test = " [mode test]" if m.test_mode else ""
            lines += [f"- {ct.first_name or ''} {ct.last_name or ''} – {ct.company or ct.email} "
                      f"({ct.sequence_code or 'sans code'}){test}", f"  « {excerpt} »"]
        lines.append("")
    if c.bounces or c.unsubscribes:
        lines.append("REBONDS ET DÉSINSCRIPTIONS")
        lines += [f"- Rebond : {ct.email} ({ct.company or '—'})" for _, ct in c.bounces]
        lines += [f"- Désinscription (STOP) : {ct.email} ({ct.company or '—'})" for _, ct in c.unsubscribes]
        lines.append("")
    if c.callbacks:
        lines.append(f"À RAPPELER AUJOURD'HUI ({len(c.callbacks)})")
        lines += [f"- {ct.first_name or ''} {ct.last_name or ''} – {ct.company or ct.email} "
                  f"(prévu le {m.callback_on:%d/%m/%Y}){' : ' + m.note if m.note else ''}" for m, ct in c.callbacks]
        lines.append("")
    lines += ["ENVOIS", f"- Envoyés aujourd'hui : {c.sent_today}", f"- Prévus demain (estimation) : {c.planned_tomorrow}",
              "", f"Classer les réponses : {BASE_URL}/v2/replies",
              "(lien utilisable sur le PC où tourne l'application)"]
    n = len(c.replies)
    subject = f"[{APP_NAME}] Récap du {day:%d/%m} : {n} réponse{'s' if n > 1 else ''}"
    return subject, "\n".join(lines)


def maybe_send(now: datetime | None = None, smtp_factory=None, force: bool = False) -> str:
    """Appelé chaque minute. Renvoie ce qui s'est passé (pour les tests et le journal)."""
    now = now or utcnow()
    smtp_factory = smtp_factory or transport.open_smtp
    with get_session() as s:
        mb = get_primary(s)
        if mb is None:
            return "no_mailbox"
        today = to_local(now).date()
        h, m = (int(x) for x in settings_store.get(s, "digest_time").split(":"))
        if not force:
            if settings_store.get(s, "digest_last_date") == today.isoformat():
                return "already_sent"
            if to_local(now).time() < time(h, m):
                return "too_early"
        content = collect(s, now)
        if not content.has_activity and not force:
            settings_store.set_(s, "digest_last_date", today.isoformat())  # rien à dire : on ne réessaie pas
            s.commit()
            return "no_activity"
        password = credentials.get_password(mb.email)
        if not password:
            return "no_password"
        subject, body = render_text(content, now)
        to = settings_store.get(s, "digest_recipient") or mb.email
        msg = compose.build_message(from_name=mb.display_name, from_email=mb.email, to_email=to,
                                    subject=subject, body=body, message_id=compose.new_message_id(mb.email))
        del msg["List-Unsubscribe"]  # email interne : pas de lien de désinscription
        cfg = server_config(as_form_values(mb), password)
    try:
        with smtp_factory(cfg) as smtp:
            smtp.send_message(msg)
    except Exception as exc:  # noqa: BLE001 – on réessaiera à la minute suivante
        log.warning("Récapitulatif non envoyé : %s", exc)
        return "error"
    with get_session() as s:
        settings_store.set_(s, "digest_last_date", today.isoformat())
        s.add(EventLog(level="info", entity="digest", text=f"Récapitulatif quotidien envoyé à {to}"))
        s.commit()
    return "sent"

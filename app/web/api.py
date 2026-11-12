"""API JSON pour l'interface V2 (React).

Principe : l'API ne contient AUCUNE règle métier. Elle appelle les mêmes
fonctions que les pages de la V1 (stats, engine, imap_sync…) et met leurs
résultats en forme JSON. Les règles restent donc testées à un seul endroit.

Les dates sont renvoyées en ISO 8601 UTC ; l'interface les affiche en heure du Maroc.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from fastapi import APIRouter
from sqlalchemy import func, select
from starlette.concurrency import run_in_threadpool

from app import (VERSION, contacts_service, engine, imap_sync, mailbox_service, replies_service, scheduler,
                 scheduling, settings_store, stats)
from app.db import get_session
from app.models import Campaign, Contact, Enrollment, Message
from app.timeutil import TZ_NAME, to_local, utcnow

router = APIRouter(prefix="/api")


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None


def _dt(v: str | None) -> datetime | None:
    return datetime.fromisoformat(v) if v else None


def _contact(c: Contact) -> dict:
    return {"id": c.id, "first_name": c.first_name, "last_name": c.last_name, "email": c.email,
            "company": c.company, "sequence_code": c.sequence_code, "phone": c.phone}


@router.get("/status")
def status():
    """Bandeau d'état, interrogé toutes les 15 secondes par l'interface."""
    now = utcnow()
    with get_session() as s:
        mb = mailbox_service.get_primary(s)
        counters = engine.counters(s, mb, now) if mb else None
        next_due = s.scalar(select(func.min(Enrollment.next_due_at))
                            .join(Campaign, Campaign.id == Enrollment.campaign_id)
                            .where(Campaign.status == "active", Enrollment.status.in_(engine.DUE_STATUSES)))
        not_before = _dt(settings_store.get(s, "engine_next_allowed_at"))
        if next_due and not_before and not_before > next_due:
            next_due = not_before
        return {
            "version": VERSION,
            "now": _iso(now),
            "timezone": TZ_NAME,
            "test_mode": settings_store.get(s, "test_mode"),
            "test_mode_locked": settings_store.test_mode_locked(),
            "mailbox": {"configured": bool(mb and mb.smtp_host and mb.imap_host),
                        "email": mb.email if mb else None, "display_name": mb.display_name if mb else None},
            "engine": {"running": scheduler.running(), "last_tick": settings_store.get(s, "engine_last_tick"),
                       "error": settings_store.get(s, "engine_last_error") or None},
            "sync": {"last_ok": settings_store.get(s, "last_imap_sync"),
                     "last_attempt": settings_store.get(s, "last_imap_attempt"),
                     "error": settings_store.get(s, "imap_last_error") or None,
                     "interval_minutes": int(imap_sync.STALE_AFTER.total_seconds() // 60)},
            "counters": counters,
            "next_send_at": _iso(next_due),
            "to_classify": stats.unclassified_count(s),
        }


@router.get("/dashboard")
def dashboard():
    now = utcnow()
    with get_session() as s:
        ind = stats.indicators(s)
        ab_rows, ab_small = stats.ab_test(s)
        queue = s.execute(
            select(Enrollment, Contact, Campaign).join(Contact, Contact.id == Enrollment.contact_id)
            .join(Campaign, Campaign.id == Enrollment.campaign_id)
            .where(Campaign.status == "active", Enrollment.status.in_(engine.DUE_STATUSES),
                   Enrollment.next_due_at < now + timedelta(days=7))
            .order_by(Enrollment.next_due_at).limit(100))
        to_review = s.execute(
            select(Enrollment, Contact, Campaign).join(Contact, Contact.id == Enrollment.contact_id)
            .join(Campaign, Campaign.id == Enrollment.campaign_id)
            .where(Enrollment.status.in_(("needs_review", "error"))).order_by(Enrollment.updated_at))
        unmatched = [
            {"id": m.id, "subject": m.subject, "excerpt": (m.body_text or "")[:220], "received_at": _iso(m.received_at),
             "suggestion": _contact(s.get(Contact, m.suggested_contact_id)) if m.suggested_contact_id else None}
            for m in s.scalars(select(Message).where(Message.kind == "unmatched").order_by(Message.received_at.desc()))]
        campaigns = []
        open_camps = list(s.scalars(select(Campaign).where(Campaign.status.in_(("active", "paused")))
                                    .order_by(Campaign.created_at.desc())))
        many = stats.indicators_many(s, [c.id for c in open_camps])  # V3 : requêtes groupées
        for c in open_camps:
            ci = many[c.id]
            campaigns.append({"id": c.id, "name": c.name, "status": c.status, "enrolled": ci.enrolled,
                              "reached": ci.reached, "replies": ci.replies, "reply_rate": ci.reply_rate,
                              "completed": ci.completed_no_reply + ci.replies + ci.bounced + ci.unsubscribed})
        days = settings_store.get(s, "followup_days")
        follow = stats.followups(s, now, scheduling.SendWindow.from_settings(s), days)
        return {
            "has_contacts": contacts_service.count_all(s) > 0,
            "followups": {"count": len(follow), "days": days},
            "indicators": {"enrolled": ind.enrolled, "reached": ind.reached, "sent_total": ind.sent_total,
                           "sent_by_step": ind.sent_by_step, "replies": ind.replies, "reply_rate": ind.reply_rate,
                           "interested": ind.interested, "bounced": ind.bounced, "unsubscribed": ind.unsubscribed,
                           "out_of_office": ind.out_of_office, "completed_no_reply": ind.completed_no_reply},
            "segments": [{"key": r.key, "reached": r.reached, "replies": r.replies, "rate": r.rate}
                         for r in stats.by_segment(s)],
            "ab": {"rows": [{"key": r.key, "reached": r.reached, "replies": r.replies, "rate": r.rate} for r in ab_rows],
                   "too_small": ab_small, "min_sample": stats.AB_MIN_SAMPLE},
            "campaigns": campaigns,
            "callbacks": [{"message_id": m.id, "callback_on": m.callback_on.isoformat(), "note": m.note,
                           "contact": _contact(c)}
                          for m, c in replies_service.due_callbacks(s, to_local(now).date())],
            "to_review": [{"enrollment_id": e.id, "status": e.status, "step": e.current_step, "error": e.last_error,
                           "contact": _contact(c), "campaign": {"id": camp.id, "name": camp.name}}
                          for e, c, camp in to_review],
            "unmatched": unmatched,
            "queue": [{"enrollment_id": e.id, "due_at": _iso(e.next_due_at), "step": e.current_step,
                       "contact": _contact(c), "campaign": {"id": camp.id, "name": camp.name}}
                      for e, c, camp in queue],
        }


@router.post("/followups/dismiss")
def followups_dismiss(body: dict):
    """V3.7.2 : retirer des personnes de « Envoyés sans réponse » (déjà relancées autrement, ou à laisser).
    Elles reviennent si vous leur écrivez de nouveau."""
    from sqlalchemy import func, select

    from app.models import Message
    ids = [int(i) for i in body.get("contact_ids") or [] if str(i).isdigit()]
    with get_session() as s:
        d = dict(settings_store.get(s, "followups_dismissed") or {})
        rows = s.execute(select(Message.contact_id, func.max(Message.sent_at))
                         .where(Message.contact_id.in_(ids), Message.direction == "out", Message.sent_at.is_not(None))
                         .group_by(Message.contact_id)).all() if ids else []
        for cid, last in rows:
            d[str(cid)] = last.isoformat()
        if len(d) > 5000:  # on garde les plus récents
            d = dict(sorted(d.items(), key=lambda kv: kv[1])[-5000:])
        settings_store.set_(s, "followups_dismissed", d)
        s.commit()
        return {"dismissed": len(rows)}


@router.post("/followups/restore")
def followups_restore(body: dict):
    """Annuler « Retirer de la liste »."""
    with get_session() as s:
        d = dict(settings_store.get(s, "followups_dismissed") or {})
        for i in body.get("contact_ids") or []:
            d.pop(str(i), None)
        settings_store.set_(s, "followups_dismissed", d)
        s.commit()
    return {"ok": True}


@router.get("/followups")
def followups(days: int | None = None):
    """Contacts à relancer à la main : dernier email il y a au moins N jours ouvrés (Réglages), aucune réponse."""
    with get_session() as s:
        days = days or settings_store.get(s, "followup_days")
        rows = stats.followups(s, utcnow(), scheduling.SendWindow.from_settings(s), max(1, min(days, 30)))
        return [{"contact": {**_contact(r["contact"]), "job_title": r["contact"].job_title},
                 "last_sent": _iso(r["last_sent"]), "business_days": r["business_days"], "step": r["step"],
                 "subject": r["subject"],
                 "campaign": {"id": r["campaign"].id, "name": r["campaign"].name} if r["campaign"] else None,
                 # V2.25 : le prochain email automatique encore prévu (toutes séquences de la personne)
                 "next_due_at": _iso(r["next"].next_due_at) if r["next"] else None,
                 "next_step": r["next"].current_step if r["next"] else None,
                 "next_campaign": {"id": r["next_campaign"].id, "name": r["next_campaign"].name} if r["next_campaign"] else None,
                 # V2.7 : l'email lui-même, pour le relire et relancer dans le même fil depuis la boîte mail
                 "message": {"id": r["message"].id, "message_id": r["message"].message_id, "body": r["message"].body_text,
                             "references": (r["message"].references_header or "").split(),
                             "test_mode": r["message"].test_mode} if r["message"] else None,
                 "days": days}
                for r in rows]


@router.post("/sync")
async def sync_now():
    report = await run_in_threadpool(imap_sync.sync)
    useful = {k: v for k, v in report.counts.items() if k not in ("ignored_own", "already_seen", "unrelated")}
    return {"ok": report.ok, "error": report.error or None, "counts": useful}


@router.post("/enrollments/{eid:int}/confirm-sent")
def confirm_sent(eid: int):
    return {"ok": engine.confirm_sent(eid)}


@router.post("/enrollments/{eid:int}/retry")
def retry(eid: int):
    return {"ok": engine.retry_now(eid)}


@router.post("/callbacks/{message_id:int}/done")
def callback_done(message_id: int):
    with get_session() as s:
        m = s.get(Message, message_id)
        if m is None:
            return {"ok": False}
        m.callback_on = None
        m.note = ((m.note + "\n") if m.note else "") + f"Rappel effectué le {to_local(utcnow()):%d/%m/%Y}"
        s.commit()
    return {"ok": True}

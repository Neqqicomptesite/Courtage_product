"""API V2 : campagnes (liste, assistant de création, contrôle avant activation, détail, actions)."""
from __future__ import annotations

from datetime import datetime, timedelta

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from starlette.concurrency import run_in_threadpool

from app import campaigns_service as camp_svc
from app import engine, stats
from app import sequences_service as ss
from app.db import get_session
from app.mailbox_service import get_primary
from app.models import Campaign, Contact, Enrollment, EventLog, Sequence
from app.scheduling import SendWindow
from app.timeutil import utcnow
from app.web.api_common import contact_ref, iso, not_found

router = APIRouter(prefix="/api")


def _camp(s, cid: int) -> Campaign:
    c = s.get(Campaign, cid)
    if c is None:
        raise not_found("Campagne")
    return c


def _ind(ind: stats.Indicators) -> dict:
    return {"enrolled": ind.enrolled, "reached": ind.reached, "sent_total": ind.sent_total,
            "sent_by_step": ind.sent_by_step, "replies": ind.replies, "reply_rate": ind.reply_rate,
            "interested": ind.interested, "bounced": ind.bounced, "unsubscribed": ind.unsubscribed,
            "out_of_office": ind.out_of_office, "completed_no_reply": ind.completed_no_reply}


@router.get("/campaigns")
def campaigns():
    with get_session() as s:
        out = []
        for c in s.scalars(select(Campaign).order_by(Campaign.created_at.desc())):
            seq = s.get(Sequence, c.sequence_id)
            out.append({"id": c.id, "name": c.name, "status": c.status, "sequence": seq.name if seq else None, "direct": c.direct,
                        "filters": c.filters or {}, "created_at": iso(c.created_at), "activated_at": iso(c.activated_at),
                        "start_at": iso(c.start_at),
                        "counts": camp_svc.enrollment_counts(s, c), "indicators": _ind(stats.indicators(s, c.id))})
        return out


class CampaignIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    sequence_id: int
    filters: dict[str, str] = {}
    stop_on_domain_reply: bool = False
    start_at: datetime | None = None  # V2.5 : démarrage planifié (ISO avec fuseau)


@router.post("/campaigns")
def campaign_create(body: CampaignIn):
    with get_session() as s:
        mb = get_primary(s)
        if mb is None:
            raise HTTPException(400, "Configurez d'abord la boîte mail dans Réglages.")
        if s.get(Sequence, body.sequence_id) is None:
            raise HTTPException(400, "Séquence introuvable.")
        filters = {k: v.strip() for k, v in body.filters.items() if k in camp_svc.FILTER_KEYS and v.strip()}
        camp = Campaign(name=body.name.strip(), mailbox_id=mb.id, sequence_id=body.sequence_id, filters=filters,
                        status="draft", stop_on_domain_reply=body.stop_on_domain_reply)
        if body.start_at is not None:
            if body.start_at.tzinfo is None:
                raise HTTPException(422, "Date de démarrage sans fuseau horaire.")
            if body.start_at < utcnow() - timedelta(minutes=5):
                raise HTTPException(422, "La date de démarrage est déjà passée.")
            camp.start_at = body.start_at
        s.add(camp)
        s.commit()
        return {"id": camp.id}


def _report_json(r: camp_svc.ActivationReport) -> dict:
    cand = lambda c: {**contact_ref(c.contact), "excluded": c.excluded, "other_campaigns": c.other_campaigns,  # noqa: E731
                      "problems": c.problems[:4], "problem_count": len(c.problems)}
    return {"eligible": len(r.eligible), "excluded": [cand(c) for c in r.excluded],
            "overlapping": [cand(c) for c in r.overlapping], "with_problems": [cand(c) for c in r.with_problems[:50]],
            "with_problems_count": len(r.with_problems), "reliability_ratio": r.reliability_ratio,
            "reliability_warn": r.reliability_ratio > camp_svc.RELIABILITY_WARN_RATIO,
            "link_warnings": r.link_warnings, "first_send": iso(r.first_send), "last_send": iso(r.last_send),
            "test_mode": r.test_mode, "blocked": r.blocked}


@router.get("/campaigns/{cid:int}/activation")
async def activation(cid: int, overlap: bool = False):
    def build():
        with get_session() as s:
            camp = _camp(s, cid)
            if camp.status not in ("draft", "active", "paused"):
                raise HTTPException(400, "Cette campagne est terminée.")
            return _report_json(camp_svc.activation_report(s, camp, include_overlapping=overlap))
    return await run_in_threadpool(build)  # rend chaque email de chaque contact : quelques secondes


class ActivateIn(BaseModel):
    overlap: bool = False


class StartIn(BaseModel):
    start_at: datetime | None = None


@router.put("/campaigns/{cid:int}/start")
def campaign_start(cid: int, body: StartIn):
    """Démarrage planifié (V2.5) : brouillon, ou campagne lancée dont aucun email n'est encore parti."""
    with get_session() as s:
        camp = _camp(s, cid)
        if body.start_at is not None and body.start_at.tzinfo is None:
            raise HTTPException(422, "Date de démarrage sans fuseau horaire.")
        try:
            moved = camp_svc.set_start(s, camp, body.start_at)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from None
        s.commit()
        return {"moved": moved, "start_at": iso(camp.start_at)}


@router.post("/campaigns/{cid:int}/activate")
async def activate(cid: int, body: ActivateIn):
    def do():
        with get_session() as s:
            camp = _camp(s, cid)
            try:
                n = camp_svc.activate(s, camp, include_overlapping=body.overlap)
            except ValueError as exc:
                raise HTTPException(409, str(exc)) from None
            s.commit()
            return {"enrolled": n}
    return await run_in_threadpool(do)


@router.get("/campaigns/{cid:int}")
def campaign_detail(cid: int):
    with get_session() as s:
        camp = _camp(s, cid)
        seq = s.get(Sequence, camp.sequence_id)
        n_steps = len(ss.steps_of(s, seq)) if seq else 0
        rows = s.execute(select(Enrollment, Contact).join(Contact, Contact.id == Enrollment.contact_id)
                         .where(Enrollment.campaign_id == camp.id)
                         .order_by(Enrollment.next_due_at.is_(None), Enrollment.next_due_at, Contact.company))
        ab_rows, ab_small = stats.ab_test(s, camp.id)
        candidates = []
        if camp.status == "draft":
            candidates = [{**contact_ref(c.contact), "excluded": c.excluded, "other_campaigns": c.other_campaigns}
                          for c in camp_svc.candidates(s, camp, check_render=False)]
        return {
            "id": camp.id, "name": camp.name, "status": camp.status, "filters": camp.filters or {}, "direct": camp.direct,
            "stop_on_domain_reply": camp.stop_on_domain_reply, "activated_at": iso(camp.activated_at),
            "start_at": iso(camp.start_at), "started": camp_svc.has_sent(s, camp),
            "sequence": {"id": seq.id, "name": seq.name, "steps": n_steps} if seq else None,
            "counts": camp_svc.enrollment_counts(s, camp), "indicators": _ind(stats.indicators(s, camp.id)),
            "segments": [{"key": r.key, "reached": r.reached, "replies": r.replies, "rate": r.rate}
                         for r in stats.by_segment(s, camp.id)],
            "ab": {"rows": [{"key": r.key, "reached": r.reached, "replies": r.replies, "rate": r.rate} for r in ab_rows],
                   "too_small": ab_small, "min_sample": stats.AB_MIN_SAMPLE},
            "candidates": candidates,
            "enrollments": [{"id": e.id, "status": e.status, "status_label": camp_svc.ENROLLMENT_LABELS[e.status],
                             "variant": e.variant_label, "step": e.current_step, "max_steps": e.max_steps, "next_due_at": iso(e.next_due_at),
                             "error": e.last_error, "contact": contact_ref(c)} for e, c in rows],
        }


@router.post("/campaigns/{cid:int}/{action}")
def campaign_action(cid: int, action: str):
    with get_session() as s:
        camp = _camp(s, cid)
        if action == "pause" and camp.status == "active":
            camp_svc.pause(s, camp)
        elif action == "resume" and camp.status == "paused":
            camp_svc.resume(s, camp)
        elif action == "delete":
            if camp.status != "draft":
                raise HTTPException(400, "Seul un brouillon peut être supprimé (mettez en pause sinon).")
            s.delete(camp)
        else:
            raise HTTPException(400, "Action impossible dans l'état actuel de la campagne.")
        s.commit()
    return {"ok": True}


# ------------------------------------------------------- actions sur une inscription

@router.post("/enrollments/{eid:int}/send-now")
async def send_now(eid: int):
    result = await run_in_threadpool(engine.tick, None, None, None, None, True, eid)
    if result.action != "sent":
        raise HTTPException(409, f"Non envoyé : {result.detail}")
    return {"detail": result.detail}


@router.post("/enrollments/{eid:int}/skip")
def skip(eid: int):
    with get_session() as s:
        enr = s.get(Enrollment, eid)
        if enr is None or enr.status not in engine.DUE_STATUSES:
            raise not_found("Inscription")
        steps = ss.steps_for(s, s.get(Sequence, s.get(Campaign, enr.campaign_id).sequence_id), enr)
        skipped = enr.current_step
        enr.current_step += 1
        if enr.current_step <= len(steps):
            nxt = steps[enr.current_step - 1]
            enr.next_due_at = SendWindow.from_settings(s).step_due(utcnow(), nxt)
            enr.status = "waiting"
        else:
            enr.status, enr.next_due_at, enr.stop_reason = "completed", None, "skipped"
        s.add(EventLog(level="info", entity="enrollment", entity_id=enr.id, text=f"Étape {skipped} sautée"))
        s.commit()
    return {"skipped": skipped}

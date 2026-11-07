"""Pages Campagnes : liste, création, détail, activation (avec confirmation), pause, reprise."""
from urllib.parse import urlencode

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from starlette.concurrency import run_in_threadpool

from app import campaigns_service as camp_svc
from app import contacts_service as cs
from app import engine, stats
from app.db import get_session
from app.mailbox_service import get_primary
from app.models import Campaign, Contact, Enrollment, EventLog, Sequence
from app.web.templating import base_context, templates

router = APIRouter(prefix="/campaigns")


def _redirect(path: str, **params) -> RedirectResponse:
    return RedirectResponse(path + (f"?{urlencode(params)}" if params else ""), status_code=303)


def _get(s, cid: int) -> Campaign:
    camp = s.get(Campaign, cid)
    if camp is None:
        raise HTTPException(404, "Campagne introuvable.")
    return camp


@router.get("")
def campaigns_list(request: Request):
    with get_session() as s:
        rows = [(c, s.get(Sequence, c.sequence_id), camp_svc.enrollment_counts(s, c))
                for c in s.scalars(select(Campaign).order_by(Campaign.created_at.desc()))]
        ctx = base_context(request, rows=rows, sequences=list(s.scalars(select(Sequence))),
                           options=cs.filter_options(s), has_mailbox=get_primary(s) is not None,
                           status_labels=camp_svc.STATUS_LABELS, error=request.query_params.get("error", ""))
    return templates.TemplateResponse(request, "campaigns_list.html", ctx)


@router.post("/new")
async def campaign_new(request: Request):
    form = await request.form()
    with get_session() as s:
        mb = get_primary(s)
        seq_id = form.get("sequence_id", "")
        if mb is None:
            return _redirect("/campaigns", error="Configurez d'abord la boîte mail dans Réglages.")
        if not seq_id.isdigit() or s.get(Sequence, int(seq_id)) is None:
            return _redirect("/campaigns", error="Choisissez une séquence.")
        camp = Campaign(name=(form.get("name") or "").strip() or "Nouvelle campagne", mailbox_id=mb.id,
                        sequence_id=int(seq_id), filters=camp_svc.filters_from_form(form), status="draft",
                        stop_on_domain_reply=form.get("stop_on_domain_reply") == "on")
        s.add(camp)
        s.commit()
        return _redirect(f"/campaigns/{camp.id}")


@router.get("/{cid:int}")
def campaign_detail(request: Request, cid: int):
    with get_session() as s:
        camp = _get(s, cid)
        seq = s.get(Sequence, camp.sequence_id)
        rows = list(s.execute(select(Enrollment, Contact).join(Contact, Contact.id == Enrollment.contact_id)
                              .where(Enrollment.campaign_id == camp.id)
                              .order_by(Enrollment.next_due_at.is_(None), Enrollment.next_due_at, Contact.company)))
        cands = camp_svc.candidates(s, camp, check_render=False) if camp.status == "draft" else []
        ab_rows, ab_too_small = stats.ab_test(s, camp.id)
        ctx = base_context(request, camp=camp, seq=seq, rows=rows, cands=cands,
                           ind=stats.indicators(s, camp.id), segments=stats.by_segment(s, camp.id),
                           ab_rows=ab_rows, ab_too_small=ab_too_small, ab_min=stats.AB_MIN_SAMPLE,
                           export_url=f"/export?campaign_id={camp.id}",
                           counts=camp_svc.enrollment_counts(s, camp), status_labels=camp_svc.STATUS_LABELS,
                           enr_labels=camp_svc.ENROLLMENT_LABELS, ok=request.query_params.get("ok", ""),
                           error=request.query_params.get("error", ""))
    return templates.TemplateResponse(request, "campaign_detail.html", ctx)


@router.get("/{cid:int}/activate")
async def campaign_activate_confirm(request: Request, cid: int, overlap: str = ""):
    def build():
        with get_session() as s:
            camp = _get(s, cid)
            if camp.status not in ("draft", "active", "paused"):
                raise HTTPException(400, "Cette campagne est terminée.")
            report = camp_svc.activation_report(s, camp, include_overlapping=overlap == "1")
            return camp, report
    # Le contrôle rend chaque email de chaque contact : quelques secondes, hors de la boucle principale.
    camp, report = await run_in_threadpool(build)
    return templates.TemplateResponse(request, "campaign_activate.html", base_context(
        request, camp=camp, report=report, overlap=overlap == "1",
        warn_ratio=camp_svc.RELIABILITY_WARN_RATIO))


@router.post("/{cid:int}/activate")
async def campaign_activate(request: Request, cid: int):
    form = await request.form()
    if form.get("confirm") != "1":
        return _redirect(f"/campaigns/{cid}/activate", overlap=form.get("overlap", ""))

    def do():
        with get_session() as s:
            camp = _get(s, cid)
            try:
                n = camp_svc.activate(s, camp, include_overlapping=form.get("overlap") == "1")
            except ValueError as exc:
                return None, str(exc)
            s.commit()
            return n, ""
    n, err = await run_in_threadpool(do)
    if err:
        return _redirect(f"/campaigns/{cid}", error=err)
    return _redirect(f"/campaigns/{cid}", ok=f"Campagne activée : {n} contact(s) inscrit(s).")


@router.post("/{cid:int}/pause")
def campaign_pause(cid: int):
    with get_session() as s:
        camp = _get(s, cid)
        if camp.status == "active":
            camp_svc.pause(s, camp)
            s.commit()
    return _redirect(f"/campaigns/{cid}", ok="Campagne en pause : plus aucun envoi.")


@router.post("/{cid:int}/resume")
def campaign_resume(cid: int):
    with get_session() as s:
        camp = _get(s, cid)
        if camp.status == "paused":
            camp_svc.resume(s, camp)
            s.commit()
    return _redirect(f"/campaigns/{cid}", ok="Campagne reprise.")


@router.post("/{cid:int}/delete")
def campaign_delete(cid: int):
    with get_session() as s:
        camp = _get(s, cid)
        if camp.status != "draft":
            return _redirect(f"/campaigns/{cid}", error="Seul un brouillon peut être supprimé (mettez en pause sinon).")
        s.delete(camp)
        s.commit()
    return _redirect("/campaigns")


# ---------------------------------------------------- actions sur une inscription

@router.post("/enrollments/{eid:int}/send-now")
async def enrollment_send_now(eid: int):
    result = await run_in_threadpool(engine.tick, None, None, None, None, True, eid)
    with get_session() as s:
        enr = s.get(Enrollment, eid)
        cid = enr.campaign_id if enr else 0
    if result.action == "sent":
        return _redirect(f"/campaigns/{cid}", ok=f"Envoyé : {result.detail}")
    return _redirect(f"/campaigns/{cid}", error=f"Non envoyé : {result.detail}")


@router.post("/enrollments/{eid:int}/confirm-sent")
def enrollment_confirm(request: Request, eid: int):
    engine.confirm_sent(eid)
    return RedirectResponse(request.headers.get("referer") or "/", status_code=303)


@router.post("/enrollments/{eid:int}/retry")
def enrollment_retry(request: Request, eid: int):
    engine.retry_now(eid)
    return RedirectResponse(request.headers.get("referer") or "/", status_code=303)


@router.post("/enrollments/{eid:int}/skip")
def enrollment_skip(eid: int):
    """Sauter l'étape en attente : on passe directement à la suivante (§6.8, file d'envoi)."""
    from app import sequences_service as ss
    from app.scheduling import SendWindow
    from app.timeutil import utcnow
    with get_session() as s:
        enr = s.get(Enrollment, eid)
        if enr is None or enr.status not in engine.DUE_STATUSES:
            raise HTTPException(404)
        camp = s.get(Campaign, enr.campaign_id)
        steps = ss.steps_for(s, s.get(Sequence, camp.sequence_id), enr)
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
        cid = camp.id
    return _redirect(f"/campaigns/{cid}", ok=f"Étape {skipped} sautée.")

"""Tableau de bord (état du moteur, éléments à vérifier) et aide délivrabilité."""
from datetime import datetime

from urllib.parse import urlencode

from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import func, select
from starlette.concurrency import run_in_threadpool

from datetime import timedelta

from app import contacts_service, engine, imap_sync, mailbox_service, replies_service, scheduler, settings_store, stats
from app.db import get_session
from app.models import Campaign, Contact, Enrollment, EventLog, Message
from app.timeutil import to_local, utcnow
from app.web.templating import base_context, templates

router = APIRouter()


def _dt(v):
    return datetime.fromisoformat(v) if v else None


@router.get("/classique")
def dashboard(request: Request):
    now = utcnow()
    with get_session() as s:
        mb = mailbox_service.get_primary(s)
        configured = mb is not None and bool(mb.smtp_host and mb.imap_host)
        n_contacts = contacts_service.count_all(s)
        counters = engine.counters(s, mb, now) if mb else None
        next_due = s.scalar(select(func.min(Enrollment.next_due_at))
                            .join(Campaign, Campaign.id == Enrollment.campaign_id)
                            .where(Campaign.status == "active", Enrollment.status.in_(engine.DUE_STATUSES)))
        to_review = list(s.execute(
            select(Enrollment, Contact, Campaign).join(Contact, Contact.id == Enrollment.contact_id)
            .join(Campaign, Campaign.id == Enrollment.campaign_id)
            .where(Enrollment.status.in_(("needs_review", "error"))).order_by(Enrollment.updated_at)))
        unmatched = [(m, s.get(Contact, m.suggested_contact_id) if m.suggested_contact_id else None)
                     for m in s.scalars(select(Message).where(Message.kind == "unmatched")
                                        .order_by(Message.received_at.desc()))]
        active_campaigns = s.scalar(select(func.count(Campaign.id)).where(Campaign.status == "active")) or 0
        queue = list(s.execute(
            select(Enrollment, Contact, Campaign).join(Contact, Contact.id == Enrollment.contact_id)
            .join(Campaign, Campaign.id == Enrollment.campaign_id)
            .where(Campaign.status == "active", Enrollment.status.in_(engine.DUE_STATUSES),
                   Enrollment.next_due_at < now + timedelta(days=7))
            .order_by(Enrollment.next_due_at).limit(100)))
        ab_rows, ab_too_small = stats.ab_test(s)
        callbacks = replies_service.due_callbacks(s, to_local(now).date())
        ctx = base_context(
            request, mailbox_configured=configured, n_contacts=n_contacts, counters=counters,
            next_due=next_due, to_review=to_review, active_campaigns=active_campaigns,
            engine_running=scheduler.running(),
            last_tick=_dt(settings_store.get(s, "engine_last_tick")),
            last_sync=_dt(settings_store.get(s, "last_imap_sync")),
            imap_error=settings_store.get(s, "imap_last_error"), unmatched=unmatched,
            flash=request.query_params.get("ok", ""),
            engine_error=settings_store.get(s, "engine_last_error"),
            not_before=_dt(settings_store.get(s, "engine_next_allowed_at")), now=now,
            ind=stats.indicators(s), segments=stats.by_segment(s), ab_rows=ab_rows, ab_too_small=ab_too_small,
            ab_min=stats.AB_MIN_SAMPLE, export_url="/export", queue=queue, callbacks=callbacks)
    return templates.TemplateResponse(request, "dashboard.html", ctx)


@router.post("/sync")
async def sync_now():
    """Bouton « Synchroniser maintenant »."""
    report = await run_in_threadpool(imap_sync.sync)
    if not report.ok:
        return RedirectResponse("/classique", status_code=303)  # l'erreur s'affiche dans le bandeau
    useful = {k: v for k, v in report.counts.items() if k not in ("ignored_own", "already_seen", "unrelated")}
    labels = {"reply": "réponse(s)", "auto_reply": "absence(s)", "bounce_hard": "rebond(s) définitif(s)",
              "bounce_soft": "rebond(s) temporaire(s)", "unsubscribe": "désinscription(s)",
              "unmatched": "réponse(s) à rattacher"}
    text = ", ".join(f"{v} {labels.get(k, k)}" for k, v in useful.items()) or "aucun nouveau message lié à vos campagnes"
    return RedirectResponse("/classique?" + urlencode({"ok": f"Synchronisation terminée : {text}."}), status_code=303)


@router.post("/replies/{message_id:int}/attach")
async def reply_attach(request: Request, message_id: int):
    form = await request.form()
    cid = form.get("contact_id", "")
    if cid.isdigit():
        imap_sync.attach(message_id, int(cid))
    return RedirectResponse(request.headers.get("referer") or "/", status_code=303)


@router.post("/replies/{message_id:int}/dismiss")
def reply_dismiss(request: Request, message_id: int):
    imap_sync.dismiss(message_id)
    return RedirectResponse(request.headers.get("referer") or "/", status_code=303)


JOURNAL_ENTITIES = {"": "Tout", "enrollment": "Envois", "contact": "Contacts", "campaign": "Campagnes",
                    "imap": "Lecture de la boîte", "engine": "Moteur", "import": "Imports", "mailbox": "Boîte mail",
                    "settings": "Réglages", "sequence": "Séquences", "digest": "Récapitulatif"}


@router.get("/journal")
def journal(request: Request, entity: str = "", level: str = "", q: str = ""):
    """Toutes les actions de l'app (§10), les plus récentes d'abord."""
    with get_session() as s:
        stmt = select(EventLog)
        if entity in JOURNAL_ENTITIES and entity:
            stmt = stmt.where(EventLog.entity == entity)
        if level in ("warning", "error"):
            stmt = stmt.where(EventLog.level.in_(("warning", "error") if level == "warning" else ("error",)))
        if q.strip():
            stmt = stmt.where(EventLog.text.ilike(f"%{q.strip()}%"))
        rows = list(s.scalars(stmt.order_by(EventLog.id.desc()).limit(300)))
    return templates.TemplateResponse(request, "journal.html", base_context(
        request, rows=rows, entity=entity, level=level, q=q, entities=JOURNAL_ENTITIES))


@router.get("/aide/delivrabilite")
def deliverability_help(request: Request):
    return templates.TemplateResponse(request, "help_deliverability.html", base_context(request))

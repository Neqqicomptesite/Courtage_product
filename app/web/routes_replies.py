"""Boîte « Réponses » (classement en un clic, HTMX) et export Excel."""
from datetime import date

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response
from starlette.concurrency import run_in_threadpool

from app import export, replies_service as rs, stats
from app.db import get_session
from app.models import Campaign, Contact, Message
from app.timeutil import to_local, utcnow
from app.web.templating import base_context, templates

router = APIRouter()


@router.get("/replies")
def replies_page(request: Request, f: str = "unclassified"):
    if f not in rs.FILTERS:
        f = "unclassified"
    with get_session() as s:
        items = rs.listing(s, f)
    return templates.TemplateResponse(request, "replies.html", base_context(
        request, items=items, f=f, filters=rs.FILTERS, classes=rs.CLASSES, today=to_local(utcnow()).date()))


def _card(request: Request, message_id: int, f: str, error: str = ""):
    with get_session() as s:
        m = s.get(Message, message_id)
        c = s.get(Contact, m.contact_id)
        count = stats.unclassified_count(s)
    hide = f == "unclassified" and m.classification is not None and not error
    return templates.TemplateResponse(request, "partials/reply_card.html", {
        "request": request, "m": m, "c": c, "classes": rs.CLASSES, "f": f, "hide": hide, "error": error,
        "count": count, "today": to_local(utcnow()).date(), "oob_count": True})


@router.post("/replies/{message_id:int}/classify")
async def classify(request: Request, message_id: int):
    form = await request.form()
    f = form.get("f", "unclassified")
    callback = None
    if form.get("callback_on"):
        try:
            callback = date.fromisoformat(form["callback_on"])
        except ValueError:
            return _card(request, message_id, f, "Date de rappel invalide.")
    with get_session() as s:
        m = s.get(Message, message_id)
        if m is None or m.contact_id is None:
            raise HTTPException(404)
        try:
            rs.classify(s, m, form.get("c", ""), utcnow(), callback, form.get("note"))
        except rs.ClassificationError as exc:
            s.rollback()
            return _card(request, message_id, f, str(exc))
        s.commit()
    return _card(request, message_id, f)


@router.post("/replies/{message_id:int}/note")
async def save_note(request: Request, message_id: int):
    form = await request.form()
    with get_session() as s:
        m = s.get(Message, message_id)
        if m is None:
            raise HTTPException(404)
        m.note = (form.get("note") or "").strip() or None
        s.commit()
    return _card(request, message_id, form.get("f", "all"))


@router.post("/replies/{message_id:int}/callback-done")
async def callback_done(request: Request, message_id: int):
    with get_session() as s:
        m = s.get(Message, message_id)
        if m is None:
            raise HTTPException(404)
        m.callback_on = None
        m.note = ((m.note + "\n") if m.note else "") + f"Rappel effectué le {to_local(utcnow()):%d/%m/%Y}"
        s.commit()
    return templates.TemplateResponse(request, "partials/empty.html", {"request": request})


# ------------------------------------------------------------------------ export

@router.get("/export")
async def export_xlsx(campaign_id: int | None = None):
    def build():
        with get_session() as s:
            name = "toutes-campagnes"
            if campaign_id:
                camp = s.get(Campaign, campaign_id)
                if camp is None:
                    raise HTTPException(404)
                name = "".join(ch if ch.isalnum() else "-" for ch in camp.name).strip("-").lower()[:40] or "campagne"
            return export.build(s, campaign_id), name
    data, name = await run_in_threadpool(build)
    filename = f"oddo-sequences_{name}_{to_local(utcnow()):%Y-%m-%d}.xlsx"
    return Response(data, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f'attachment; filename="{filename}"'})

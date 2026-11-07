"""API V2 : réponses, journal, réglages, graphiques."""
from __future__ import annotations

from datetime import date, datetime, time, timedelta

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select
from starlette.concurrency import run_in_threadpool

from app import mailbox_browser as mbx_labels
from app import credentials, imap_sync, mailbox_service, settings_store
from app import replies_service as rs
from app.db import get_session
from app.mail import transport
from app.models import Contact, EventLog, Message
from app.timeutil import TZ, to_local, utcnow
from app.web.api_common import FormLike, contact_ref, iso, not_found
from app.web.routes_pages import JOURNAL_ENTITIES
from app.web.routes_settings import CAP_WARNING, _read_mailbox_form, read_sending_form

router = APIRouter(prefix="/api")


# --------------------------------------------------------------------- graphique

@router.get("/activity")
def activity(days: int = 30):
    """Envois et réponses par jour (heure du Maroc), pour le graphique du tableau de bord."""
    days = max(7, min(days, 90))
    today = to_local(utcnow()).date()
    start_day = today - timedelta(days=days - 1)
    start = datetime.combine(start_day, time(0), tzinfo=TZ)
    end = datetime.combine(today + timedelta(days=1), time(0), tzinfo=TZ)
    series = {start_day + timedelta(days=i): {"sent": 0, "replies": 0} for i in range(days)}
    with get_session() as s:
        for (ts,) in s.execute(select(Message.sent_at).where(
                Message.direction == "out", Message.enrollment_id.is_not(None),  # emails de campagne seulement
                Message.sent_at >= start, Message.sent_at < end)):
            series[to_local(ts).date()]["sent"] += 1
        for (ts,) in s.execute(select(Message.received_at).where(
                Message.direction == "in", Message.kind == "reply",
                Message.received_at >= start, Message.received_at < end)):
            series[to_local(ts).date()]["replies"] += 1
    return [{"day": d.isoformat(), **v} for d, v in series.items()]


# ---------------------------------------------------------------------- réponses

def _reply(m: Message, c: Contact) -> dict:
    return {"id": m.id, "kind": m.kind, "subject": m.subject, "text": m.body_text,
            "full": m.body_full if m.body_full and m.body_full != m.body_text else None,
            "received_at": iso(m.received_at), "classification": m.classification,
            "callback_on": iso(m.callback_on), "note": m.note, "return_date": m.return_date,
            "test_mode": m.test_mode, "contact": contact_ref(c),
            "message_id": m.message_id, "references": (m.references_header or "").split()}


@router.get("/replies")
def replies(f: str = "unclassified"):
    if f not in rs.FILTERS:
        f = "unclassified"
    with get_session() as s:
        counts = {k: len(rs.listing(s, k)) for k in rs.FILTERS}
        unmatched = [{"id": m.id, "subject": m.subject, "text": m.body_text, "received_at": iso(m.received_at),
                      "suggestion": contact_ref(s.get(Contact, m.suggested_contact_id)) if m.suggested_contact_id else None}
                     for m in s.scalars(select(Message).where(Message.kind == "unmatched")
                                        .order_by(Message.received_at.desc()))]
        return {"filter": f, "filters": [{"key": k, "label": v, "count": counts[k]} for k, v in rs.FILTERS.items()],
                "classes": [{"key": k, "label": v} for k, v in rs.CLASSES.items()],
                "items": [_reply(m, c) for m, c in rs.listing(s, f)], "unmatched": unmatched}


class ClassifyIn(BaseModel):
    classification: str
    callback_on: date | None = None
    note: str | None = None


@router.post("/replies/{mid:int}/classify")
def classify(mid: int, body: ClassifyIn):
    with get_session() as s:
        m = s.get(Message, mid)
        if m is None or m.contact_id is None:
            raise not_found("Réponse")
        try:
            rs.classify(s, m, body.classification, utcnow(), body.callback_on, body.note)
        except rs.ClassificationError as exc:
            raise HTTPException(400, str(exc)) from None
        s.commit()
        return _reply(m, s.get(Contact, m.contact_id))


class NoteIn(BaseModel):
    note: str


@router.put("/replies/{mid:int}/note")
def reply_note(mid: int, body: NoteIn):
    with get_session() as s:
        m = s.get(Message, mid)
        if m is None:
            raise not_found("Réponse")
        m.note = body.note.strip() or None
        s.commit()
    return {"ok": True}


class AttachIn(BaseModel):
    contact_id: int


@router.post("/replies/{mid:int}/attach")
def reply_attach(mid: int, body: AttachIn):
    return {"ok": imap_sync.attach(mid, body.contact_id)}


@router.post("/replies/{mid:int}/dismiss")
def reply_dismiss(mid: int):
    return {"ok": imap_sync.dismiss(mid)}


# ----------------------------------------------------------------------- journal

@router.get("/journal")
def journal(entity: str = "", level: str = "", q: str = "", limit: int = 300):
    with get_session() as s:
        stmt = select(EventLog)
        if entity and entity in JOURNAL_ENTITIES:
            stmt = stmt.where(EventLog.entity == entity)
        if level in ("warning", "error"):
            stmt = stmt.where(EventLog.level.in_(("warning", "error") if level == "warning" else ("error",)))
        if q.strip():
            stmt = stmt.where(EventLog.text.ilike(f"%{q.strip()}%"))
        rows = s.scalars(stmt.order_by(EventLog.id.desc()).limit(max(10, min(limit, 1000))))
        return {"entities": [{"value": k, "label": v} for k, v in JOURNAL_ENTITIES.items()],
                "items": [{"id": e.id, "ts": iso(e.ts), "level": e.level, "entity": e.entity, "entity_id": e.entity_id,
                           "text": e.text} for e in rows]}


# ----------------------------------------------------------------------- réglages

@router.get("/settings")
def settings_get():
    with get_session() as s:
        mb = mailbox_service.get_primary(s)
        values = mailbox_service.as_form_values(mb)
        st = settings_store.get_all(s)
        return {
            "mailbox": {k: values[k] for k in ("display_name", "email", "smtp_host", "smtp_port", "smtp_security",
                                                "imap_host", "imap_port", "username", "sent_folder", "watched_folders",
                                                "signature")},
            "mailbox_exists": mb is not None,
            "has_password": bool(mb) and credentials.has_password(mb.email),
            "folders": [{**f, "display": mbx_labels.folder_label(f["raw"], f.get("display") or f["raw"])["label"]}
                        for f in st["imap_folders_cache"] if isinstance(f, dict) and f.get("raw")],
            "sending": {
                "send_days": st["send_days"], "send_windows": st["send_windows"],
                "holidays": st["holidays"], "daily_cap": values["daily_cap"], "hourly_cap": values["hourly_cap"],
                "min_gap_s": values["min_gap_s"], "max_gap_s": values["max_gap_s"],
                "rampup_enabled": st["rampup_enabled"], "rampup_per_day": st["rampup_per_day"],
                "unsubscribe_line": st["unsubscribe_line"], "unsubscribe_enabled": st["unsubscribe_enabled"],
                "digest_time": st["digest_time"],
                "digest_recipient": st["digest_recipient"], "auto_reply_continues": st["auto_reply_continues"],
                "followup_days": st["followup_days"],
            },
            "test_mode": settings_store.get(s, "test_mode"), "test_mode_locked": settings_store.test_mode_locked(),
            "cap_warning": CAP_WARNING,
        }


@router.put("/settings/mailbox")
def settings_mailbox(body: dict):
    form = FormLike(body)
    values, errors = _read_mailbox_form(form)
    password = body.get("password") or ""
    with get_session() as s:
        mb = mailbox_service.get_primary(s)
        current = mailbox_service.as_form_values(mb)
        for k in ("daily_cap", "hourly_cap", "min_gap_s", "max_gap_s"):
            values[k] = current[k]
        if not password and not (mb and credentials.has_password(mb.email)):
            errors["password"] = "Le mot de passe est obligatoire."
        if errors:
            raise HTTPException(422, {"errors": errors})
        try:
            mailbox_service.save(s, values, password or None)
            s.add(EventLog(level="info", entity="mailbox", text="Réglages de la boîte mail enregistrés"))
            s.commit()
        except mailbox_service.MailboxTaken as exc:
            s.rollback()
            raise HTTPException(409, {"errors": {"email": str(exc)}}) from None
        except credentials.CredentialError as exc:
            s.rollback()
            raise HTTPException(500, {"errors": {"password": str(exc)}}) from None
    return {"ok": True}


@router.put("/settings/sending")
def settings_sending(body: dict):
    # Les plages et jours fériés arrivent structurés ; la validation V1 attend le format formulaire.
    windows = body.get("send_windows") or []
    flat = dict(body)
    for i, w in enumerate(windows[:2], start=1):
        flat[f"w{i}_start"], flat[f"w{i}_end"] = w[0], w[1]
    flat["holidays"] = "\n".join(f"{h['date']} {h.get('label', '')}".strip() for h in body.get("holidays") or [])
    flat["send_days"] = [str(d) for d in body.get("send_days") or []]
    values, errors = read_sending_form(FormLike(flat))
    try:  # V2.7 : seuil « sans réponse » (pas dans le formulaire de l'ancienne interface)
        followup_days = int(body.get("followup_days", 3))
        if not 1 <= followup_days <= 30:
            raise ValueError
    except (TypeError, ValueError):
        errors["followup_days"] = "Entre 1 et 30 jours ouvrés."
        followup_days = 3
    with get_session() as s:
        mb = mailbox_service.get_primary(s)
        if mb is None:
            errors["mailbox"] = "Enregistrez d'abord la boîte mail."
        if errors:
            raise HTTPException(422, {"errors": errors})
        for k in ("daily_cap", "hourly_cap", "min_gap_s", "max_gap_s"):
            setattr(mb, k, values.pop(k))
        for k, v in values.items():
            settings_store.set_(s, k, v)
        settings_store.set_(s, "followup_days", followup_days)
        if "unsubscribe_enabled" in body:  # V2.12 : ligne STOP facultative
            settings_store.set_(s, "unsubscribe_enabled", bool(body["unsubscribe_enabled"]))
        s.add(EventLog(level="info", entity="settings", text="Réglages d'envoi enregistrés"))
        s.commit()
    return {"ok": True}


class TestModeIn(BaseModel):
    enabled: bool


@router.put("/settings/test-mode")
def settings_test_mode(body: TestModeIn):
    if not body.enabled and settings_store.test_mode_locked():
        raise HTTPException(409, "Mode test verrouillé pendant le développement de la V2.")
    with get_session() as s:
        settings_store.set_(s, "test_mode", body.enabled)
        s.add(EventLog(level="warning" if not body.enabled else "info", entity="settings",
                       text=f"Mode test {'ACTIVÉ' if body.enabled else 'DÉSACTIVÉ – envois réels'}"))
        s.commit()
    return {"test_mode": body.enabled}


@router.post("/settings/test-connection")
async def settings_test_connection(body: dict):
    values, errors = _read_mailbox_form(FormLike(body))
    password = body.get("password") or ""
    with get_session() as s:
        mb = mailbox_service.get_primary(s)
        if not password and mb:
            password = credentials.get_password(mb.email) or ""
    if not password:
        errors["password"] = "Saisissez le mot de passe pour tester."
    if errors:
        raise HTTPException(422, {"errors": errors})
    cfg = mailbox_service.server_config(values, password)
    report = await run_in_threadpool(transport.check_connection, cfg, bool(body.get("send_test_email", True)))
    folders = [{"raw": f.raw_name, "display": mbx_labels.folder_label(f.raw_name, f.display_name)["label"]} for f in report.folders]
    with get_session() as s:
        if folders:
            settings_store.set_(s, "imap_folders_cache", folders)
        s.add(EventLog(level="info" if report.ok else "warning", entity="mailbox",
                       text="Test de connexion : " + " | ".join(f"{st.label} {'OK' if st.ok else 'ÉCHEC'}"
                                                                for st in report.steps)))
        s.commit()
    return {"ok": report.ok, "steps": [{"label": st.label, "ok": st.ok, "detail": st.detail} for st in report.steps],
            "folders": folders, "sent_folder": report.sent_folder, "junk_folder": report.junk_folder}

"""API V2.8 : pièces jointes, logos des entreprises, agenda (rappels) et centre de notifications."""
from __future__ import annotations

import secrets
import zlib
from datetime import date, datetime, timedelta
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import select

from app import attachments_service, replies_service, scheduling, settings_store, stats
from app.db import get_session
from app.models import REMINDER_KINDS, Attachment, Campaign, Company, Contact, Enrollment, Message, Reminder
from app.paths import data_dir
from app.timeutil import to_local, utcnow
from app.web.api_common import contact_ref, iso, not_found

router = APIRouter(prefix="/api")


def _name(c: Contact) -> str:
    return " ".join(x for x in (c.first_name, c.last_name) if x) or c.email

# ---------------------------------------------------------------- pièces jointes



def _day(d) -> str:
    """« jeudi 12/11 à 09:00 » (heure locale), pour la cloche."""
    from app.timeutil import to_local
    jours = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
    x = to_local(d)
    return f"{jours[x.weekday()]} {x:%d/%m} à {x:%H:%M}"

@router.post("/attachments")
async def attachment_upload(file: UploadFile = File(...)):
    data = await file.read(attachments_service.MAX_EMAIL_BYTES + 1)
    with get_session() as s:
        try:
            att = attachments_service.save(s, file.filename or "piece-jointe", data, file.content_type)
        except attachments_service.AttachmentError as exc:
            raise HTTPException(422, {"errors": {"file": str(exc)}}) from None
        s.commit()
        return attachments_service.as_json(att)


@router.get("/attachments/{aid:int}")
def attachment_download(aid: int, t: str = ""):
    """V3 (revue externe, point 8) : le jeton aléatoire de la pièce jointe est exigé, sinon
    n'importe quel employé connecté pouvait tout télécharger en faisant défiler les numéros."""
    with get_session() as s:
        att = s.get(Attachment, aid)
        if att is None or not secrets.compare_digest(t, att.token or "") or not attachments_service.path_of(att).is_file():
            raise not_found("Pièce jointe")
        return FileResponse(attachments_service.path_of(att), media_type=att.content_type, filename=att.filename)


# ---------------------------------------------------------------- logos

LOGO_TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp",
              ".svg": "image/svg+xml"}
LOGO_MAX = 2 * 1024 * 1024


def logos_dir() -> Path:
    d = data_dir() / "logos"
    d.mkdir(parents=True, exist_ok=True)
    return d


@router.post("/companies/{cid:int}/logo")
async def logo_upload(cid: int, file: UploadFile = File(...)):
    ext = Path(file.filename or "").suffix.lower()
    if ext not in LOGO_TYPES:
        raise HTTPException(422, {"errors": {"file": "Logo au format PNG, JPG, WEBP ou SVG."}})
    data = await file.read(LOGO_MAX + 1)
    if not data:
        raise HTTPException(422, {"errors": {"file": "Fichier vide."}})
    if len(data) > LOGO_MAX:
        raise HTTPException(422, {"errors": {"file": "Logo trop lourd : 2 Mo au maximum."}})
    with get_session() as s:
        comp = s.get(Company, cid)
        if comp is None:
            raise not_found("Entreprise")
        # nouveau nom à chaque envoi : le navigateur ne garde pas l'ancien logo en cache
        name = f"{cid}-{secrets.token_hex(4)}{ext}"
        (logos_dir() / name).write_bytes(data)
        comp.logo = name  # l'ancien fichier reste dans data/logos (aucune suppression)
        s.commit()
        return {"logo": f"/api/companies/{cid}/logo?v={name}"}


@router.get("/companies/{cid:int}/logo")
def logo_get(cid: int):
    with get_session() as s:
        comp = s.get(Company, cid)
        if comp is None or not comp.logo or not (logos_dir() / comp.logo).is_file():
            raise not_found("Logo")
        p = logos_dir() / comp.logo
        # SVG : affiché comme image, jamais exécuté comme page (aucun script)
        return FileResponse(p, media_type=LOGO_TYPES.get(p.suffix.lower(), "application/octet-stream"),
                            headers={"Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'",
                                     "Cache-Control": "max-age=31536000, immutable"})


@router.delete("/companies/{cid:int}/logo")
def logo_delete(cid: int):
    with get_session() as s:
        comp = s.get(Company, cid)
        if comp is None:
            raise not_found("Entreprise")
        comp.logo = None
        s.commit()
        return {"ok": True}


# ---------------------------------------------------------------- agenda

KIND_LABELS = {"call": "Appeler", "email": "Envoyer un email", "quote": "Relancer un devis",
               "meeting": "Rendez-vous", "renewal": "Renouvellement de contrat", "other": "Autre"}
assert set(KIND_LABELS) == set(REMINDER_KINDS)


def _company_ref(c: Company | None) -> dict | None:
    return {"id": c.id, "name": c.name, "kind": c.kind} if c else None


def _reminder_json(s, r: Reminder) -> dict:
    contact = s.get(Contact, r.contact_id) if r.contact_id else None
    company = s.get(Company, r.company_id) if r.company_id else None
    if company is None and contact and contact.company_id:
        company = s.get(Company, contact.company_id)
    return {"id": r.id, "source": "reminder", "kind": r.kind, "kind_label": KIND_LABELS[r.kind], "title": r.title,
            "notes": r.notes or "", "due_on": r.due_on.isoformat(), "due_time": r.due_time,
            "done": r.done_at is not None, "done_at": iso(r.done_at), "created_at": iso(r.created_at),
            "contact": contact_ref(contact), "company": _company_ref(company),
            "quote_case_id": r.quote_case_id,  # Dossiers de cotation : rappel lié à un dossier de cotation
            "contract_id": r.contract_id}      # Contrats : rappel de préavis


def _parse(body: dict, partial: bool = False) -> dict:
    out, errors = {}, {}
    if "kind" in body or not partial:
        k = body.get("kind") or "other"
        if k not in REMINDER_KINDS:
            errors["kind"] = "Type inconnu."
        out["kind"] = k
    if "title" in body or not partial:
        t = " ".join(str(body.get("title") or "").split())
        if not t:
            errors["title"] = "Indiquez ce qu'il faut faire."
        out["title"] = t[:255]
    if "notes" in body:
        out["notes"] = str(body.get("notes") or "")
    if "due_on" in body or not partial:
        try:
            out["due_on"] = date.fromisoformat(str(body.get("due_on") or ""))
        except ValueError:
            errors["due_on"] = "Date invalide."
    if "due_time" in body:
        t = (body.get("due_time") or "").strip() or None
        if t:
            try:
                t = datetime.strptime(t, "%H:%M").strftime("%H:%M")
            except ValueError:
                errors["due_time"] = "Heure invalide (HH:MM)."
        out["due_time"] = t
    for f in ("contact_id", "company_id", "quote_case_id"):  # Dossiers de cotation : rappel lié à un dossier
        if f in body:
            out[f] = int(body[f]) if body.get(f) else None
    if errors:
        raise HTTPException(422, {"errors": errors})
    return out


@router.get("/reminders")
def reminders(start: str | None = None, end: str | None = None, contact_id: int | None = None,
              company_id: int | None = None, include_done: bool = True):
    """Rappels de l'agenda entre deux dates (incluses), plus les « À rappeler plus tard »
    posés depuis les réponses (lecture seule ici : ils se traitent dans Réponses)."""
    today = to_local(utcnow()).date()
    d0 = date.fromisoformat(start) if start else today - timedelta(days=31)
    d1 = date.fromisoformat(end) if end else today + timedelta(days=62)
    with get_session() as s:
        q = select(Reminder).where(Reminder.due_on >= d0, Reminder.due_on <= d1)
        if contact_id:
            q = q.where(Reminder.contact_id == contact_id)
        if company_id:
            ids = select(Contact.id).where(Contact.company_id == company_id)
            q = q.where((Reminder.company_id == company_id) | Reminder.contact_id.in_(ids))
        if not include_done:
            q = q.where(Reminder.done_at.is_(None))
        items = [_reminder_json(s, r) for r in s.scalars(q.order_by(Reminder.due_on, Reminder.due_time, Reminder.id))]
        cq = (select(Message, Contact).join(Contact, Contact.id == Message.contact_id)
              .where(Message.classification == "later", Message.callback_on.is_not(None),
                     Message.callback_on >= d0, Message.callback_on <= d1))
        if contact_id:
            cq = cq.where(Contact.id == contact_id)
        if company_id:
            cq = cq.where(Contact.company_id == company_id)
        for m, c in s.execute(cq.order_by(Message.callback_on)):
            items.append({"id": m.id, "source": "callback", "kind": "call", "kind_label": "Rappeler (réponse)",
                          "title": f"Rappeler {_name(c)}", "notes": m.note or "",
                          "due_on": m.callback_on.isoformat(), "due_time": None, "done": False, "done_at": None,
                          "created_at": iso(m.received_at), "contact": contact_ref(c),
                          "company": _company_ref(s.get(Company, c.company_id) if c.company_id else None)})
        items.sort(key=lambda x: (x["due_on"], x["due_time"] or "99:99"))
        return {"items": items, "kinds": [{"value": k, "label": v} for k, v in KIND_LABELS.items()],
                "today": today.isoformat()}


@router.post("/reminders")
def reminder_create(body: dict):
    data = _parse(body)
    with get_session() as s:
        if data.get("contact_id") and s.get(Contact, data["contact_id"]) is None:
            raise not_found("Contact")
        if data.get("company_id") and s.get(Company, data["company_id"]) is None:
            raise not_found("Entreprise")
        from app.current import user_id
        r = Reminder(**data, user_id=user_id())
        s.add(r)
        s.commit()
        return _reminder_json(s, r)


@router.put("/reminders/{rid:int}")
def reminder_update(rid: int, body: dict):
    data = _parse(body, partial=True)
    with get_session() as s:
        r = s.get(Reminder, rid)
        if r is None:
            raise not_found("Rappel")
        for k, v in data.items():
            setattr(r, k, v)
        if "done" in body:
            r.done_at = utcnow() if body["done"] else None
        s.commit()
        return _reminder_json(s, r)


@router.delete("/reminders/{rid:int}")
def reminder_delete(rid: int):
    with get_session() as s:
        r = s.get(Reminder, rid)
        if r is None:
            raise not_found("Rappel")
        s.delete(r)
        s.commit()
        return {"ok": True}


# ---------------------------------------------------------------- notifications

SEEN_MAX = 800


def build_notifications(s, now: datetime | None = None) -> list[dict]:
    """Tout ce qui demande une action, du plus urgent au moins urgent. Chaque élément a une clé
    stable : une fois vu, il ne compte plus dans la pastille (mais reste dans la liste tant que
    l'action n'est pas faite)."""
    now = now or utcnow()
    today = to_local(now).date()
    out: list[dict] = []

    for r in s.scalars(select(Reminder).where(Reminder.done_at.is_(None), Reminder.due_on <= today)
                       .order_by(Reminder.due_on, Reminder.due_time)):
        c = s.get(Contact, r.contact_id) if r.contact_id else None
        late = (today - r.due_on).days
        who = f" · {_name(c)}" if c else ""
        out.append({"key": f"rem:{r.id}:{r.due_on.isoformat()}", "type": "reminder", "level": "warning" if late else "info",
                    "title": r.title,
                    "detail": (f"{KIND_LABELS[r.kind]} · " if r.kind != "other" else "")
                              + ("Aujourd'hui" if not late else f"En retard de {late} jour(s)")
                              + (f" à {r.due_time}" if r.due_time and not late else "") + who,
                    "href": f"/quotes/{r.quote_case_id}" if r.quote_case_id else f"/contracts/{r.contract_id}" if r.contract_id
                    else f"/agenda?d={r.due_on.isoformat()}&r={r.id}",
                    "at": r.due_on.isoformat(),
                    "reminder_id": r.id})

    for m, c in replies_service.due_callbacks(s, today):
        out.append({"key": f"cb:{m.id}:{m.callback_on.isoformat()}", "type": "callback", "level": "warning",
                    "title": f"Rappeler {_name(c)}",
                    "detail": (m.note or "Demandé dans sa réponse") + (f" · {c.company}" if c.company else ""),
                    "href": f"/contacts?open={c.id}", "at": m.callback_on.isoformat()})

    # V3.8 : listes qu'un collègue m'a confiées, tant qu'aucune campagne n'est lancée dessus (30 jours)
    from app import lists_service
    from app.models import AppUser as _U
    for cl in lists_service.assigned_to_me(s, now - timedelta(days=30)):
        by = s.get(_U, cl.assigned_by)
        n = lists_service.counts(s, [cl.id]).get(cl.id, 0)
        out.append({"key": f"list:{cl.id}:{cl.assigned_at.isoformat()}", "type": "list", "level": "warning",
                    "title": f"{(by.full_name or by.email) if by else 'Un collègue'} vous a confié {n} contact{'s' if n > 1 else ''}",
                    "detail": f"Liste « {cl.name} »" + (f" · {cl.assign_note[:120]}" if cl.assign_note else "")
                              + " · prête pour une campagne",
                    "href": f"/campaigns/new?list_id={cl.id}", "at": iso(cl.assigned_at)})

    days = settings_store.get(s, "followup_days")
    for row in stats.followups(s, now, scheduling.SendWindow.from_settings(s), days):
        c = row["contact"]
        out.append({"key": f"fu:{c.id}:{to_local(row['last_sent']).date().isoformat()}", "type": "followup", "level": "info",
                    "title": f"{_name(c)} n'a pas répondu",
                    "detail": f"Email envoyé il y a {row['business_days']} jours ouvrés"
                              + (f" · {c.company}" if c.company else "") + (f" · « {row['subject']} »" if row["subject"] else "")
                              + (f" · relance auto prévue {_day(row['next'].next_due_at)}" if row["next"] else ""),
                    "href": f"/inbox/followups?contact={c.id}", "at": iso(row["last_sent"])})

    up = (settings_store.get(s, "update_status") or {}).get("available")
    if up:
        from app import VERSION, updater
        if updater.parse_version(up) > updater.parse_version(VERSION):
            out.append({"key": f"maj:{up}", "type": "update", "level": "info",
                        "title": f"Nouvelle version disponible : {up}",
                        "detail": "Réglages → Mise à jour → Installer et redémarrer (vos données ne bougent pas)",
                        "href": "/settings?s=update", "at": None})

    n = stats.unclassified_count(s)
    if n:
        out.append({"key": f"cls:{n}:{today.isoformat()}", "type": "replies", "level": "warning",
                    "title": f"{n} réponse(s) à trier", "detail": "Indiquez ce que chaque personne a répondu",
                    "href": "/replies", "at": None})

    for e, c, camp in s.execute(select(Enrollment, Contact, Campaign).join(Contact, Contact.id == Enrollment.contact_id)
                                .join(Campaign, Campaign.id == Enrollment.campaign_id)
                                .where(Enrollment.status.in_(("needs_review", "error")))):
        out.append({"key": f"enr:{e.id}:{e.status}:{iso(e.updated_at)}", "type": "error", "level": "error",
                    "title": f"{_name(c)} : envoi bloqué" if e.status == "error"
                             else f"{_name(c)} : envoi à vérifier",
                    "detail": f"{camp.name}" + (f" · {e.last_error}" if e.last_error else ""),
                    "href": f"/campaigns/{camp.id}", "at": iso(e.updated_at)})

    for key, label, href in (("engine_last_error", "Envoi automatique en erreur", "/settings?s=mailbox"),
                             ("imap_last_error", "Lecture de la boîte mail en erreur", "/settings?s=mailbox")):
        err = settings_store.get(s, key)
        if err:
            out.append({"key": f"{key}:{zlib.crc32(str(err).encode()):x}", "type": "error", "level": "error", "title": label,
                        "detail": str(err)[:200], "href": href, "at": None})
    return out


@router.get("/notifications")
def notifications():
    with get_session() as s:
        items = build_notifications(s)
        seen = set(settings_store.get(s, "notifications_seen") or [])
        for it in items:
            it["seen"] = it["key"] in seen
        return {"items": items, "unseen": sum(not it["seen"] for it in items)}


@router.post("/notifications/seen")
def notifications_seen(body: dict | None = None):
    """Marque comme vues les clés données (ou toutes les notifications actuelles)."""
    with get_session() as s:
        keys = (body or {}).get("keys") or [it["key"] for it in build_notifications(s)]
        seen = [k for k in settings_store.get(s, "notifications_seen") or [] if k not in keys] + list(keys)
        settings_store.set_(s, "notifications_seen", seen[-SEEN_MAX:])
        s.commit()
        return {"ok": True}


# ------------------------------------------------------------------ V2.16 : guide de démarrage

GUIDE_KEYS = ("mailbox", "signature", "test", "contacts", "real")


def guide_progress(s) -> dict:
    """Où en est la personne dans « Bien démarrer ». Chaque étape est cochée d'elle-même quand
    l'application peut le constater ; sinon la personne la coche à la main (`guide_checked`).
    V2.22 : une étape faite le reste (`guide_done`) : repasser en mode test, ou une boîte
    momentanément illisible, ne fait pas réapparaître la barre du tableau de bord."""
    from app import mailbox_service
    mb = mailbox_service.get_primary(s)
    manual = set(settings_store.get(s, "guide_checked") or [])
    done_before = set(settings_store.get(s, "guide_done") or [])
    sent = s.scalars(select(Message.id).where(Message.direction == "out")).first() is not None
    sent_real = s.scalars(select(Message.id).where(Message.direction == "out", Message.test_mode.is_(False))).first() is not None
    prospects = s.scalars(select(Contact.id).where(Contact.kind == "prospect")).first() is not None
    auto = {
        "mailbox": bool(mb and mb.smtp_host and mb.imap_host and settings_store.get(s, "last_imap_sync")
                        and not settings_store.get(s, "imap_last_error")),
        "signature": bool(mb and (mb.signature or "").strip()),
        "test": sent,
        "contacts": prospects,
        "real": not settings_store.get(s, "test_mode") or sent_real,
    }
    steps = {k: bool(auto[k] or k in manual or k in done_before) for k in GUIDE_KEYS}
    reached = {k for k, v in steps.items() if v and k not in manual}
    if not reached <= done_before:
        settings_store.set_(s, "guide_done", sorted(done_before | reached))
        s.commit()
    return {"steps": steps, "done": sum(steps.values()), "total": len(GUIDE_KEYS)}


@router.get("/guide")
def guide_get():
    with get_session() as s:
        return guide_progress(s)


@router.post("/guide")
def guide_check(body: dict):
    key, done = body.get("key"), bool(body.get("done", True))
    if key not in ("test", "contacts"):
        raise HTTPException(400, "Cette étape se coche d'elle-même.")
    with get_session() as s:
        checked = [k for k in settings_store.get(s, "guide_checked") or [] if k != key] + ([key] if done else [])
        settings_store.set_(s, "guide_checked", checked)
        s.commit()
        return guide_progress(s)


# ------------------------------------------------------------------ V2.17 : mises à jour
# V3 : mises à jour par fichier .zip et sauvegardes SQLite : propres au poste unique. Sur le
# serveur, elles permettraient d'installer du code ou d'écrire n'importe où : fermées (404).
# Le serveur se met à jour depuis GitHub et sauvegarde PostgreSQL (deploy/).

def _pc_only() -> None:
    from app.paths import is_server_mode
    if is_server_mode():
        raise HTTPException(404, "Indisponible sur le serveur en ligne.")


@router.get("/update")
def update_status():
    _pc_only()
    from app import updater
    return updater.status()


@router.post("/update/url")
def update_url(body: dict):
    _pc_only()
    from app import updater
    url = (body.get("url") or "").strip()
    if url:
        try:
            updater.download_url(url)
        except updater.UpdateError as e:
            raise HTTPException(400, str(e)) from e
    with get_session() as s:
        settings_store.set_(s, "update_url", url)
        settings_store.set_(s, "update_status", {})
        s.commit()
    return updater.status()


@router.post("/update/check")
def update_check():
    _pc_only()
    from app import updater
    return updater.check()


@router.post("/update/install")
def update_install():
    _pc_only()
    from app import updater
    try:
        return updater.install()
    except updater.UpdateError as e:
        raise HTTPException(400, str(e)) from e


# ------------------------------------------------------------------ V2.20 : sauvegardes

@router.get("/backups")
def backups_list():
    _pc_only()
    from pathlib import Path

    from app import backup
    with get_session() as s:
        target = settings_store.get(s, "backup_copy_dir") or ""
    copies = sorted(Path(target).glob("oddo_*.db")) if target and Path(target).is_dir() else []
    return {"items": backup.listing(), "copy_dir": target, "copy_dir_ok": bool(target and Path(target).is_dir()),
            "copies": len(copies), "last_copy": copies[-1].name if copies else None}


@router.post("/backups/now")
def backups_now():
    _pc_only()
    from app import backup
    path = backup.backup_now("manuelle")
    if path is None:
        raise HTTPException(400, "Aucune base à sauvegarder.")
    return backups_list()


@router.post("/backups/copy-dir")
def backups_copy_dir(body: dict):
    _pc_only()
    from pathlib import Path
    target = (body.get("path") or "").strip().strip('"')
    if target:
        p = Path(target)
        if not p.is_absolute() or not p.is_dir():
            raise HTTPException(400, "Dossier introuvable : collez le chemin complet d'un dossier qui existe "
                                     "(par exemple celui de Google Drive ou de OneDrive sur ce PC).")
        try:
            probe = p / ".oddo-test-ecriture"
            probe.write_bytes(b"ok")
            probe.unlink()
        except OSError as e:
            raise HTTPException(400, f"Impossible d'écrire dans ce dossier : {e}") from e
    with get_session() as s:
        settings_store.set_(s, "backup_copy_dir", target)
        s.commit()
    if target:
        from app import backup
        backup.backup_now("manuelle")  # première copie tout de suite
    return backups_list()

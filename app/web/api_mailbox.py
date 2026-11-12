"""API V2.4 : la boîte mail complète (lecture seule) et l'écriture d'emails depuis l'application."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from sqlalchemy import select

from app import mailbox_browser as mbx
from app import manual_mail
from app.db import get_session
from app.models import Company, Contact, Message
from app.web.api_common import contact_ref

router = APIRouter(prefix="/api/mailbox")


def _unavailable(exc: mbx.MailboxUnavailable) -> HTTPException:
    return HTTPException(503, str(exc))


def _own() -> set[str]:
    """V3.8 : vos propres adresses (jamais affichées comme un prospect ou un contact)."""
    from app import address_book
    with get_session() as s:
        return address_book._own_addresses(s)


def _people(emails: set[str], own: set[str] | None = None) -> dict[str, dict]:
    """Expéditeurs connus : contact, entreprise et type, pour les badges de la liste."""
    emails = {e for e in emails if e} - (own if own is not None else _own())
    if not emails:
        return {}
    with get_session() as s:
        out = {}
        for c in s.scalars(select(Contact).where(Contact.email.in_(emails))):
            comp = s.get(Company, c.company_id) if c.company_id else None
            out[c.email] = {**contact_ref(c), "kind": c.kind, "status": c.global_status,
                            "company_ref": {"id": comp.id, "name": comp.name} if comp else None}
        return out


def _campaign_replies(message_ids: set[str]) -> dict[str, dict]:
    """Emails déjà repérés par la synchronisation comme réponses de campagne."""
    ids = {m for m in message_ids if m}
    if not ids:
        return {}
    with get_session() as s:
        return {m.message_id: {"id": m.id, "kind": m.kind, "classification": m.classification}
                for m in s.scalars(select(Message).where(Message.direction == "in", Message.message_id.in_(ids)))}


@router.get("/folders")
def folders():
    try:
        return mbx.folders()
    except mbx.MailboxUnavailable as exc:
        raise _unavailable(exc) from None


@router.get("/messages")
def messages(folder: str = "INBOX", days: int = 30, refresh: bool = False, q: str = ""):
    """V3.4.4 : jusqu'à 365 jours. Avec `q`, le serveur mail cherche sur toute la période (au-delà
    des 200 emails les plus récents affichés sinon). Rien n'est stocké chez nous."""
    crit = mbx.search_criteria(q[:120])
    if q.strip() and not crit:
        return {"folder": folder, "days": days, "searched": True, "items": [], "found": 0, "truncated": False,
                "fetched_at": None, "unsearchable": True}
    try:
        data = mbx.list_messages(folder, max(1, min(days, 365)), refresh, criteria=crit)
    except mbx.MailboxUnavailable as exc:
        raise _unavailable(exc) from None
    own = _own()
    people = _people({m["from_email"] for m in data["items"]} | {a for m in data["items"] for a in m["to"]}, own)
    replies = _campaign_replies({m["message_id"] for m in data["items"]})
    items = []
    for m in data["items"]:
        # Dans « Envoyés » (ou un email de vous rangé ailleurs), la personne intéressante est le destinataire.
        mine = m["from_email"].lower() in own
        who = m["from_email"] if m["from_email"] in people or not m["to"] else next((a for a in m["to"] if a in people), m["from_email"])
        items.append({**m, "from_me": mine, "contact": people.get(who), "campaign_reply": replies.get(m["message_id"])})
    return {**data, "items": items}


@router.get("/messages/{uid:int}")
def message(uid: int, folder: str = "INBOX"):
    try:
        m = mbx.get_message(folder, uid)
    except mbx.MailboxUnavailable as exc:
        raise _unavailable(exc) from None
    own = _own()
    people = _people({m["from_email"], *m["to"], *m["cc"]}, own)
    return {**m, "from_me": m["from_email"].lower() in own,
            "contact": people.get(m["from_email"]) or next((people[a] for a in m["to"] if a in people), None),
            "campaign_reply": _campaign_replies({m["message_id"]}).get(m["message_id"])}


@router.get("/messages/{uid:int}/part/{index:int}")
def message_part(uid: int, index: int, folder: str = "INBOX", download: int = 0):
    """V2.19 : pièce jointe ou image d'un email, lue depuis le serveur (rien n'est écrit sur le disque).
    Images, PDF et texte s'affichent dans le navigateur ; tout le reste est téléchargé, et rien
    ne peut exécuter de code dans l'application (type forcé, nosniff, CSP « sandbox »)."""
    from urllib.parse import quote
    try:
        data, ctype, name = mbx.get_part(folder, uid, index)
    except mbx.MailboxUnavailable as exc:
        raise _unavailable(exc) from None
    show = ctype in mbx.VIEWABLE and not download
    disposition = "inline" if show else "attachment"
    media = ctype if show else "application/octet-stream"
    if media == "text/plain":
        media = "text/plain; charset=utf-8"
    headers = {"Content-Disposition": f"{disposition}; filename*=UTF-8''{quote(name, safe='')}",
               "X-Content-Type-Options": "nosniff", "Cache-Control": "private, max-age=300"}
    if ctype != "application/pdf":  # la visionneuse PDF du navigateur ne fonctionne pas en « sandbox »
        headers["Content-Security-Policy"] = "default-src 'none'; img-src 'self' data:; style-src 'unsafe-inline'; sandbox"
    return Response(data, media_type=media, headers=headers)


@router.get("/messages/{uid:int}/preview/{index:int}")
def message_part_preview(uid: int, index: int, folder: str = "INBOX"):
    """V3 : aperçu d'une pièce jointe (PDF, image, Word, Excel, CSV, texte) avant téléchargement."""
    from app import attachment_preview
    try:
        data, ctype, name = mbx.get_part(folder, uid, index)
    except mbx.MailboxUnavailable as exc:
        raise _unavailable(exc) from None
    return {"name": name, "type": ctype, "size": len(data), **attachment_preview.preview(data, ctype, name)}


@router.post("/messages/{uid:int}/forward")
def message_forward(uid: int, folder: str = "INBOX"):
    """V2.19 : prépare le transfert d'un email : ses pièces jointes (et photos intégrées) sont
    rangées comme des pièces jointes d'envoi, prêtes à repartir avec le message transféré."""
    from app import attachments_service
    try:
        parts = mbx.forwardable_parts(folder, uid)
    except mbx.MailboxUnavailable as exc:
        raise _unavailable(exc) from None
    saved, skipped, total = [], [], 0
    with get_session() as s:
        for data, ctype, name in parts:
            if total + len(data) > attachments_service.MAX_EMAIL_BYTES:
                skipped.append(f"{name} : 10 Mo au total dépassés, à joindre autrement")
                continue
            try:
                saved.append(attachments_service.as_json(attachments_service.save(s, name, data, ctype)))
                total += len(data)
            except attachments_service.AttachmentError as exc:
                skipped.append(f"{name} : {exc}")
        s.commit()
    return {"attachments": saved, "skipped": skipped}


@router.post("/messages/{uid:int}/archive")
def archive_message(uid: int, folder: str = "INBOX"):
    """V2.20 : « Archiver », comme dans Outlook : l'email est déplacé dans le dossier d'archives
    du serveur (jamais supprimé). La boîte est relue juste avant, pour qu'une réponse à une
    campagne archivée aussitôt arrête quand même les relances."""
    from app import imap_sync
    from app.timeutil import utcnow
    try:
        imap_sync.sync(utcnow())
    except Exception:  # noqa: BLE001 – la lecture échouée n'empêche pas d'archiver
        pass
    try:
        return mbx.archive(folder, uid)
    except mbx.MailboxUnavailable as exc:
        raise _unavailable(exc) from None


@router.get("/unread")
def unread(refresh: bool = False):
    """V3.7.1 : nombre d'emails non lus de la boîte de réception (pastille du menu)."""
    try:
        return {"unread": mbx.unread_count(refresh)}
    except mbx.MailboxUnavailable:
        return {"unread": None}


@router.post("/messages/{uid:int}/seen")
def mark_seen(uid: int, folder: str = "INBOX", seen: bool = True):
    """V3.7.1 : lu / non lu, sur le serveur (le webmail le voit aussi)."""
    try:
        mbx.set_seen(folder, uid, seen)
    except mbx.MailboxUnavailable as exc:
        raise _unavailable(exc) from None
    return {"ok": True, "seen": seen}


@router.post("/messages/{uid:int}/spam")
def spam_message(uid: int, folder: str = "INBOX"):
    """V3 : « Spam » : l'email part dans le dossier des indésirables de la boîte (comme dans
    Outlook), jamais supprimé ; annulable."""
    try:
        return mbx.archive(folder, uid, kind="junk")
    except mbx.MailboxUnavailable as exc:
        raise _unavailable(exc) from None


@router.post("/unarchive")
def unarchive_message(body: dict):
    kind = "junk" if body.get("kind") == "junk" else "archive"
    try:
        ok = mbx.unarchive((body.get("message_id") or "").strip(), (body.get("folder") or "INBOX").strip(), kind=kind)
    except mbx.MailboxUnavailable as exc:
        raise _unavailable(exc) from None
    if not ok:
        raise HTTPException(404, "Email introuvable dans les archives.")
    return {"ok": True}


@router.post("/send")
def send(body: dict):
    d = manual_mail.draft_from(body)
    with get_session() as s:
        try:
            out = manual_mail.send(s, d)
        except manual_mail.SendRefused as exc:
            s.rollback()
            if exc.confirm:
                raise HTTPException(409, {"message": exc.confirm, "confirm": True}) from None
            raise HTTPException(422, {"errors": exc.errors}) from None
        return {"id": out.id, "test_mode": out.test_mode, "to": out.to_email}


@router.get("/suggest")
def suggest(q: str = "", exclude: str = ""):
    """V3.7 : adresses proposées pendant la saisie d'un destinataire (À, Cc, Cci)."""
    from app import address_book
    with get_session() as s:
        return {"items": address_book.suggest(s, q, exclude=[e for e in exclude.split(",") if e.strip()])}


@router.get("/awaiting")
def awaiting(refresh: bool = False):
    """V2.12 : emails reçus restés sans réponse de votre part depuis N jours ouvrés."""
    from app import awaiting as aw
    try:
        data = aw.awaiting(refresh=refresh)
    except mbx.MailboxUnavailable as exc:
        raise _unavailable(exc) from None
    # même forme qu'un email de la boîte (fiche du contact, réponse de campagne) pour le lecteur
    people = _people({i["from_email"] for i in data["items"]})
    replies = _campaign_replies({i["message_id"] for i in data["items"]})
    data["items"] = [{**i, "contact": people.get(i["from_email"]), "campaign_reply": replies.get(i["message_id"])}
                     for i in data["items"]]
    return data


@router.post("/awaiting/dismiss")
def awaiting_dismiss(body: dict):
    """V2.13 : ranger des emails « À répondre » (on n'y répondra pas, ou c'est déjà fait autrement)."""
    from app import awaiting as aw
    items = [i for i in body.get("items") or [] if isinstance(i, dict)]
    return {"dismissed": aw.dismiss(items)}


@router.post("/awaiting/restore")
def awaiting_restore(body: dict):
    from app import awaiting as aw
    aw.restore([str(e) for e in body.get("senders") or []])
    return {"ok": True}


@router.get("/with")
def mails_with(email: str, days: int = 365):
    """V2.14 : les derniers emails échangés avec une personne (reçus et envoyés), pour sa fiche.
    V3.4.4 : cherchés par le serveur mail sur un an (avant : parmi les 200 plus récents de 90 jours)."""
    email = email.strip().lower()
    with get_session() as s:
        from app.mailbox_service import get_primary
        mb = get_primary(s)
        sent_folder = mb.sent_folder if mb else None
    out = []
    try:
        for folder in ["INBOX", *([sent_folder] if sent_folder else [])]:
            for m in mbx.list_messages(folder, max(7, min(days, 365)), criteria=mbx.search_criteria(person=email))["items"]:
                if m["from_email"] == email or email in m["to"]:
                    out.append({"folder": folder, "uid": m["uid"], "subject": m["subject"], "date": m["date"],
                                "direction": "in" if m["from_email"] == email else "out",
                                "has_attachments": m.get("has_attachments", False)})
    except mbx.MailboxUnavailable as exc:
        raise _unavailable(exc) from None
    out.sort(key=lambda x: x["date"] or "", reverse=True)
    return {"items": out[:15], "days": days}

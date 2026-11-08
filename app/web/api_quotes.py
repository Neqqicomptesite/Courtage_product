"""API des dossiers de cotation (voir app/quotes.py)."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from sqlalchemy import func, select

from app import quotes
from app.db import get_session
from app.models import Company, Contact, QuoteCase, QuoteFile, QuoteInsurer
from app.web.api_common import not_found, require_admin_or_owner

router = APIRouter(prefix="/api/quotes")


def _err(exc: quotes.QuoteError) -> HTTPException:
    return HTTPException(422, {"errors": exc.errors})


def _case(s, cid: int) -> QuoteCase:
    case = s.get(QuoteCase, cid)
    if case is None:
        raise not_found("Dossier")
    return case


def _insurer(s, case: QuoteCase, iid: int) -> QuoteInsurer:
    qi = s.get(QuoteInsurer, iid)
    if qi is None or qi.case_id != case.id:
        raise not_found("Compagnie du dossier")
    return qi


@router.get("")
def list_cases(company_id: int | None = None, contact_id: int | None = None):
    with get_session() as s:
        items = quotes.list_json(s)
        if company_id is not None:
            items = [i for i in items if i["company_id"] == company_id]
        if contact_id is not None:
            items = [i for i in items if i["contact_id"] == contact_id]
        return {"items": items, "stages": [{"key": k, "label": v} for k, v in quotes.STAGE_LABELS.items()],
                "branches": [b["name"] for b in quotes.branches()]}


@router.get("/branches")
def branches():
    return {"items": quotes.branches()}


@router.get("/people")
def people():
    """Employés actifs du cabinet, pour choisir le responsable d'un dossier (vide en poste unique)."""
    from app.models import AppUser
    with get_session() as s:
        return {"items": [{"id": u.id, "name": u.full_name or u.email}
                          for u in s.scalars(select(AppUser).where(AppUser.active.is_(True)).order_by(AppUser.full_name))]}


@router.get("/insurer-companies")
def insurer_companies():
    """Compagnies d'assurance de la base, pour choisir qui consulter."""
    with get_session() as s:
        counts = dict(s.execute(select(Contact.company_id, func.count(Contact.id)).where(Contact.company_id.is_not(None))
                                .group_by(Contact.company_id)).all())
        return {"items": [{"id": c.id, "name": c.name, "contacts": counts.get(c.id, 0),
                           "logo": f"/api/companies/{c.id}/logo?v={c.logo}" if c.logo else None}
                          for c in s.scalars(select(Company).where(Company.kind == "insurer").order_by(Company.name))]}


@router.post("")
def create_case(body: dict):
    with get_session() as s:
        try:
            case = quotes.create(s, body)
        except quotes.QuoteError as exc:
            raise _err(exc) from None
        if body.get("insurer_ids"):
            quotes.add_insurers(s, case, body["insurer_ids"], body.get("insurer_branches"))
        s.commit()
        return quotes.detail_json(s, case)


@router.get("/{cid:int}")
def get_case(cid: int):
    with get_session() as s:
        return quotes.detail_json(s, _case(s, cid))


@router.patch("/{cid:int}")
def update_case(cid: int, body: dict):
    with get_session() as s:
        case = _case(s, cid)
        try:
            quotes.update(s, case, body)
        except quotes.QuoteError as exc:
            s.rollback()
            raise _err(exc) from None
        s.commit()
        return quotes.detail_json(s, case)


@router.delete("/{cid:int}")
def delete_case(cid: int):
    with get_session() as s:
        case = _case(s, cid)
        require_admin_or_owner(case.owner_id, "Seul le responsable du dossier ou l'administrateur peut le supprimer.")
        s.delete(case)
        s.commit()
        return {"ok": True}


@router.post("/{cid:int}/notes")
def add_note(cid: int, body: dict):
    text = str(body.get("text") or "").strip()
    if not text:
        raise HTTPException(422, {"errors": {"text": "La note est vide."}})
    with get_session() as s:
        case = _case(s, cid)
        quotes.event(s, case, "note", text[:4000])
        case.updated_at = quotes.utcnow()
        s.commit()
        return quotes.detail_json(s, case)


@router.post("/{cid:int}/insurers")
def add_insurers(cid: int, body: dict):
    with get_session() as s:
        case = _case(s, cid)
        quotes.add_insurers(s, case, [int(x) for x in body.get("company_ids") or []], body.get("branches"))
        s.commit()
        return quotes.detail_json(s, case)


@router.patch("/{cid:int}/insurers/{iid:int}")
def update_insurer(cid: int, iid: int, body: dict):
    with get_session() as s:
        case = _case(s, cid)
        try:
            quotes.set_insurer(s, case, _insurer(s, case, iid), body)
        except quotes.QuoteError as exc:
            s.rollback()
            raise _err(exc) from None
        s.commit()
        return quotes.detail_json(s, case)


@router.delete("/{cid:int}/insurers/{iid:int}")
def remove_insurer(cid: int, iid: int):
    with get_session() as s:
        case = _case(s, cid)
        try:
            quotes.remove_insurer(s, case, _insurer(s, case, iid))
        except quotes.QuoteError as exc:
            raise _err(exc) from None
        s.commit()
        return quotes.detail_json(s, case)


def _ids(raw) -> list[int]:
    if isinstance(raw, str):
        raw = raw.split(",")
    try:
        return [int(x) for x in raw or [] if str(x).strip()]
    except ValueError:
        raise HTTPException(422, {"errors": {"insurer_ids": "Liste invalide."}}) from None


@router.post("/{cid:int}/draft")
def draft(cid: int, body: dict):
    """Email à relire pour une compagnie : les lignes (branches) choisies, et éventuellement les
    destinataires choisis (sinon ceux de la dernière fois, ou le service souscription)."""
    with get_session() as s:
        case = _case(s, cid)
        try:
            rows = quotes.rows_for(s, case, _ids(body.get("insurer_ids")))
        except quotes.QuoteError as exc:
            raise _err(exc) from None
        to = body.get("to")
        return quotes.draft(s, case, rows, [str(e) for e in to] if isinstance(to, list) else None)


@router.post("/{cid:int}/send")
def send(cid: int, body: dict):
    from app import manual_mail
    with get_session() as s:
        case = _case(s, cid)
        try:
            rows = quotes.rows_for(s, case, _ids(body.get("insurer_ids")))
            quotes.send(s, case, rows, body)
        except quotes.QuoteError as exc:
            s.rollback()
            raise _err(exc) from None
        except manual_mail.SendRefused as exc:
            s.rollback()
            if exc.confirm:
                raise HTTPException(409, {"message": exc.confirm, "confirm": True}) from None
            raise HTTPException(422, {"errors": exc.errors}) from None
        return quotes.detail_json(s, case)


@router.post("/{cid:int}/send-all")
def send_all(cid: int, body: dict | None = None):
    """Envoie d'un coup toutes les demandes « À envoyer » (un email commun par compagnie)."""
    with get_session() as s:
        case = _case(s, cid)
        ids = (body or {}).get("company_ids")
        report = quotes.send_all(s, case, [int(x) for x in ids] if ids else None)
        s.commit()
        return {"report": report, "quote": quotes.detail_json(s, case)}


@router.post("/{cid:int}/reminders")
def add_reminder(cid: int, body: dict):
    with get_session() as s:
        case = _case(s, cid)
        try:
            quotes.add_reminder(s, case, body)
        except quotes.QuoteError as exc:
            s.rollback()
            raise _err(exc) from None
        s.commit()
        return quotes.detail_json(s, case)


@router.post("/{cid:int}/files")
def add_file(cid: int, body: dict):
    with get_session() as s:
        case = _case(s, cid)
        try:
            quotes.add_file(s, case, int(body.get("attachment_id") or 0), str(body.get("kind") or "client"),
                            str(body.get("label") or ""), int(body["insurer_id"]) if body.get("insurer_id") else None)
        except quotes.QuoteError as exc:
            s.rollback()
            raise _err(exc) from None
        s.commit()
        return quotes.detail_json(s, case)


@router.post("/{cid:int}/files/from-mail")
def add_file_from_mail(cid: int, body: dict):
    """Range dans le dossier une pièce jointe reçue (offre d'une compagnie…), depuis la boîte de l'employé."""
    from app import attachments_service
    from app import mailbox_browser as mbx
    with get_session() as s:
        case = _case(s, cid)
        try:
            data, ctype, name = mbx.get_part(str(body.get("folder") or "INBOX"), int(body["uid"]), int(body["index"]))
        except mbx.MailboxUnavailable as exc:
            raise HTTPException(503, str(exc)) from None
        except (KeyError, ValueError, LookupError):
            raise not_found("Pièce jointe") from None
        try:
            att = attachments_service.save(s, name, data, ctype)
            quotes.add_file(s, case, att.id, str(body.get("kind") or "offer"), str(body.get("label") or ""),
                            int(body["insurer_id"]) if body.get("insurer_id") else None)
        except (attachments_service.AttachmentError, quotes.QuoteError) as exc:
            s.rollback()
            raise HTTPException(422, {"errors": {"file": str(exc)}}) from None
        s.commit()
        return quotes.detail_json(s, case)


@router.delete("/{cid:int}/files/{fid:int}")
def remove_file(cid: int, fid: int):
    with get_session() as s:
        case = _case(s, cid)
        f = s.get(QuoteFile, fid)
        if f is None or f.case_id != case.id:
            raise not_found("Document")
        quotes.event(s, case, "file", "Document retiré du dossier")
        s.delete(f)  # le fichier lui-même reste (il peut avoir été envoyé par email)
        s.commit()
        return quotes.detail_json(s, case)

"""V3.9.2 : brouillons des emails écrits dans l'appli.

Enregistrés tout seuls pendant la frappe (fenêtre « Nouveau message », réponse, transfert) : fermer
la fenêtre ne perd plus rien. Chaque employé ne voit que les siens (en poste unique : user_id vide).
Envoyer l'email supprime son brouillon. Les pièces jointes restent dans data/attachments (jamais
supprimées) : le brouillon garde seulement leurs numéros.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import MailDraft
from app.timeutil import utcnow

MAX_DRAFTS = 200
DATA_KEYS = ("cc", "bcc", "in_reply_to", "references", "quote", "forward", "with_quote", "signature", "attachment_ids")


def _uid():
    from app.current import user_id
    return user_id()


def _mine(q):
    uid = _uid()
    return q.where(MailDraft.user_id.is_(None) if uid is None else MailDraft.user_id == uid)


def get(s: Session, draft_id: int) -> MailDraft | None:
    return s.scalars(_mine(select(MailDraft).where(MailDraft.id == draft_id))).first()


def is_empty(body: dict) -> bool:
    return not any(str(body.get(k) or "").strip() for k in ("to", "cc", "bcc", "subject", "body")) \
        and not body.get("attachment_ids")


def save(s: Session, body: dict, draft_id: int | None = None) -> MailDraft:
    """Crée ou met à jour un brouillon. Un numéro inconnu (supprimé, ou d'un collègue) en crée un nouveau."""
    d = get(s, draft_id) if draft_id else None
    if d is None:
        d = MailDraft(user_id=_uid(), created_at=utcnow())
        s.add(d)
    d.to_addr = str(body.get("to") or "")[:5000]
    d.subject = str(body.get("subject") or "")[:500]
    d.body = str(body.get("body") or "")[:200_000]
    data = {k: body[k] for k in DATA_KEYS if k in body}
    data["attachment_ids"] = [int(x) for x in (data.get("attachment_ids") or []) if str(x).isdigit()][:30]
    d.data = data
    d.updated_at = utcnow()
    s.flush()
    old = s.scalars(_mine(select(MailDraft).order_by(MailDraft.updated_at.desc())).offset(MAX_DRAFTS)).all()
    for o in old:  # au-delà de 200 : les plus anciens partent
        s.delete(o)
    return d


def delete(s: Session, draft_id: int) -> bool:
    d = get(s, draft_id)
    if d is None:
        return False
    s.delete(d)
    return True


def as_json(s: Session, d: MailDraft, full: bool = False) -> dict:
    out = {"id": d.id, "to": d.to_addr, "subject": d.subject, "updated_at": d.updated_at.isoformat() if d.updated_at else None,
           "snippet": " ".join((d.body or "").split())[:160], "attachments_count": len((d.data or {}).get("attachment_ids") or [])}
    if full:
        from app import attachments_service
        data = dict(d.data or {})
        atts = attachments_service.get_many(s, data.pop("attachment_ids", []) or [])
        out.update(body=d.body, **{k: v for k, v in data.items()}, attachments=[attachments_service.as_json(a) for a in atts])
    return out


def listing(s: Session) -> list[dict]:
    return [as_json(s, d) for d in s.scalars(_mine(select(MailDraft).order_by(MailDraft.updated_at.desc())))]

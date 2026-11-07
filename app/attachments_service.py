"""Pièces jointes (V2.8) : un fichier déposé une fois, réutilisable dans une étape de
séquence ou un email écrit à la main.

- Rangées dans data/attachments/<jeton>/<nom du fichier> (jamais sur Internet).
- 10 Mo au plus par email, toutes pièces confondues : au-delà, beaucoup de serveurs
  refusent l'email, et une grosse pièce jointe envoyée en nombre ressemble à du spam.
- Jamais supprimées : l'historique des emails envoyés y fait référence.
"""
from __future__ import annotations

import mimetypes
import re
import secrets
import unicodedata
from email.message import EmailMessage
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Attachment, StepAttachment
from app.paths import data_dir

MAX_EMAIL_BYTES = 10 * 1024 * 1024
BLOCKED_EXT = {".exe", ".bat", ".cmd", ".com", ".js", ".vbs", ".scr", ".msi", ".ps1", ".jar"}


class AttachmentError(ValueError):
    pass


def root() -> Path:
    d = data_dir() / "attachments"
    d.mkdir(parents=True, exist_ok=True)
    return d


def clean_name(name: str) -> str:
    name = Path(name or "piece-jointe").name.strip() or "piece-jointe"
    name = unicodedata.normalize("NFC", name)
    name = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "_", name)
    return name[:180]


def save(s: Session, filename: str, data: bytes, content_type: str | None = None) -> Attachment:
    name = clean_name(filename)
    if Path(name).suffix.lower() in BLOCKED_EXT:
        raise AttachmentError("Ce type de fichier est bloqué par les messageries (programme exécutable).")
    if not data:
        raise AttachmentError("Fichier vide.")
    if len(data) > MAX_EMAIL_BYTES:
        raise AttachmentError("Fichier trop lourd : 10 Mo au maximum par email.")
    token = secrets.token_hex(12)
    folder = root() / token
    folder.mkdir()
    (folder / name).write_bytes(data)
    ctype = content_type if content_type and "/" in content_type else (mimetypes.guess_type(name)[0] or "application/octet-stream")
    att = Attachment(token=token, filename=name, content_type=ctype, size=len(data))
    s.add(att)
    s.flush()
    return att


def path_of(att: Attachment) -> Path:
    return root() / att.token / att.filename


def read(att: Attachment) -> bytes:
    p = path_of(att)
    if not p.is_file():
        raise AttachmentError(f"Pièce jointe introuvable sur le disque : {att.filename}")
    return p.read_bytes()


def get_many(s: Session, ids: list[int]) -> list[Attachment]:
    if not ids:
        return []
    found = {a.id: a for a in s.scalars(select(Attachment).where(Attachment.id.in_(ids)))}
    missing = [i for i in ids if i not in found]
    if missing:
        raise AttachmentError("Pièce jointe introuvable.")
    return [found[i] for i in ids]


def of_step(s: Session, step_id: int) -> list[Attachment]:
    return list(s.scalars(select(Attachment).join(StepAttachment, StepAttachment.attachment_id == Attachment.id)
                          .where(StepAttachment.step_id == step_id).order_by(StepAttachment.id)))


def set_step(s: Session, step_id: int, ids: list[int]) -> None:
    atts = get_many(s, list(dict.fromkeys(ids)))
    check_total(atts)
    for link in s.scalars(select(StepAttachment).where(StepAttachment.step_id == step_id)):
        s.delete(link)
    s.flush()
    for a in atts:
        s.add(StepAttachment(step_id=step_id, attachment_id=a.id))


def check_total(atts: list[Attachment]) -> None:
    if sum(a.size for a in atts) > MAX_EMAIL_BYTES:
        raise AttachmentError("Pièces jointes trop lourdes : 10 Mo au maximum par email, toutes pièces confondues.")


def attach(msg: EmailMessage, atts: list[Attachment]) -> list[str]:
    """Ajoute les fichiers à l'email ; renvoie leurs noms (pour l'historique)."""
    for a in atts:
        maintype, _, subtype = a.content_type.partition("/")
        msg.add_attachment(read(a), maintype=maintype or "application", subtype=subtype or "octet-stream",
                           filename=a.filename)
    return [a.filename for a in atts]


def as_json(a: Attachment) -> dict:
    return {"id": a.id, "name": a.filename, "size": a.size, "type": a.content_type}

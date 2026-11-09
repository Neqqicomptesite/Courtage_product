"""Boîte « Réponses » : liste, classement en un clic, notes, rappels (§6.8)."""
from __future__ import annotations

from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import suppression
from app.imap_sync import stop_open_enrollments
from app.models import Contact, EventLog, Message

CLASSES = {
    "interested": "Intéressé",
    "later": "À rappeler plus tard",
    "not_interested": "Pas intéressé",
    "out_of_office": "Absent",
    "wrong_contact": "Mauvais contact",
    "unsubscribe": "Désinscription",
}
LISTED_KINDS = ("reply", "unsubscribe", "auto_reply")
# « Non classées » = à traiter. Une réponse marquée comme lue en sort (et ne compte plus dans la
# notification) sans être classée : on la retrouve sous « Lues, non classées » et dans « Toutes ».
FILTERS = {"unclassified": "Non classées", "seen": "Lues, non classées", "all": "Toutes", **CLASSES}


def listing(s: Session, flt: str = "unclassified") -> list[tuple[Message, Contact]]:
    q = (select(Message, Contact).join(Contact, Contact.id == Message.contact_id)
         .where(Message.direction == "in", Message.kind.in_(LISTED_KINDS)))
    if flt == "unclassified":
        q = q.where(Message.classification.is_(None), Message.seen_at.is_(None))
    elif flt == "seen":
        q = q.where(Message.classification.is_(None), Message.seen_at.is_not(None))
    elif flt in CLASSES:
        q = q.where(Message.classification == flt)
    return list(s.execute(q.order_by(Message.received_at.desc())))


def mark_seen(s: Session, ids: list[int] | None, seen: bool, now) -> int:
    """Marque comme lues (ou non lues) des réponses sans les classer. ids=None : toutes les
    réponses non classées encore à traiter. Renvoie le nombre de réponses modifiées."""
    q = select(Message).where(Message.direction == "in", Message.kind.in_(LISTED_KINDS),
                              Message.classification.is_(None))
    if ids is None:
        q = q.where(Message.seen_at.is_(None))
    else:
        q = q.where(Message.id.in_(ids))
    n = 0
    for m in s.scalars(q):
        m.seen_at = now if seen else None
        n += 1
    return n


class ClassificationError(ValueError):
    pass


def classify(s: Session, msg: Message, classification: str, now, callback_on: date | None = None,
             note: str | None = None) -> None:
    if classification not in CLASSES:
        raise ClassificationError("Classement inconnu.")
    if classification == "later" and callback_on is None:
        raise ClassificationError("Indiquez la date de rappel.")
    contact = s.get(Contact, msg.contact_id)
    msg.classification, msg.classified_at = classification, now
    msg.callback_on = callback_on if classification == "later" else None
    if note is not None:
        msg.note = note.strip() or None
    # Effets : classer « Désinscription » ou « Mauvais contact » protège pour l'avenir.
    if classification == "unsubscribe" and not msg.test_mode:
        contact.global_status = "unsubscribed"
        suppression.add(s, contact.email, "Désinscription (classement manuel)")
        stop_open_enrollments(s, contact, "unsubscribed", "unsubscribe")
    elif classification == "wrong_contact" and not msg.test_mode:
        if contact.global_status in ("active", "replied"):
            contact.global_status = "do_not_contact"
        stop_open_enrollments(s, contact, "stopped", "wrong_contact")
    s.add(EventLog(level="info", entity="contact", entity_id=contact.id,
                   text=f"Réponse classée : {CLASSES[classification]}"
                        + (f" (rappel le {callback_on:%d/%m/%Y})" if callback_on and classification == 'later' else "")))


def due_callbacks(s: Session, today: date) -> list[tuple[Message, Contact]]:
    return list(s.execute(
        select(Message, Contact).join(Contact, Contact.id == Message.contact_id)
        .where(Message.classification == "later", Message.callback_on <= today)
        .order_by(Message.callback_on)))

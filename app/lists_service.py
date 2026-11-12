"""V3.6 : listes de contacts.

Une liste est personnelle (son auteur la voit et la modifie) et peut être partagée : toute l'équipe
la voit et peut s'en servir pour une campagne ; seuls son auteur et l'administrateur la modifient.
Elle se remplit à l'import (une liste par fichier), à la main depuis Contacts, ou depuis une
campagne (les sans-réponse). Supprimer une liste ne supprime aucun contact.
"""
from __future__ import annotations

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.current import is_admin, user_id
from app.models import AppUser, Contact, ContactList, ContactListMember, Enrollment
from app.timeutil import utcnow


class ListError(ValueError):
    pass


def can_edit(cl: ContactList) -> bool:
    uid = user_id()
    return uid is None or cl.owner_id == uid or cl.owner_id is None or is_admin()


def _check_name(name: str) -> str:
    name = " ".join((name or "").split())
    if not name:
        raise ListError("Donnez un nom à la liste.")
    return name[:120]


def create(s: Session, name: str, contact_ids=(), source: str = "manual", shared: bool = False) -> ContactList:
    cl = ContactList(name=_check_name(name), owner_id=user_id(), source=source, shared=shared)
    s.add(cl)
    s.flush()
    add(s, cl, contact_ids)
    return cl


def add(s: Session, cl: ContactList, contact_ids) -> int:
    """Ajoute les contacts qui n'y sont pas encore ; renvoie combien ont été ajoutés."""
    ids = {int(i) for i in contact_ids or ()}
    if not ids:
        return 0
    ids &= set(s.scalars(select(Contact.id).where(Contact.id.in_(ids))))
    have = set(s.scalars(select(ContactListMember.contact_id).where(ContactListMember.list_id == cl.id,
                                                                   ContactListMember.contact_id.in_(ids))))
    new = ids - have
    s.add_all(ContactListMember(list_id=cl.id, contact_id=c) for c in sorted(new))
    if new:
        cl.updated_at = utcnow()
    return len(new)


def remove(s: Session, cl: ContactList, contact_ids) -> int:
    ids = [int(i) for i in contact_ids or ()]
    if not ids:
        return 0
    n = s.execute(delete(ContactListMember).where(ContactListMember.list_id == cl.id,
                                                  ContactListMember.contact_id.in_(ids))).rowcount or 0
    cl.updated_at = utcnow()
    return n


def rename(cl: ContactList, name: str) -> None:
    cl.name = _check_name(name)


def from_campaign_no_reply(s: Session, camp, name: str | None = None) -> ContactList:
    """Les contacts allés au bout de la campagne sans répondre (et toujours joignables)."""
    ids = list(s.scalars(select(Enrollment.contact_id).join(Contact, Contact.id == Enrollment.contact_id).where(
        Enrollment.campaign_id == camp.id, Enrollment.status == "completed", Contact.global_status == "active")))
    if not ids:
        raise ListError("Personne n'est allé au bout de cette campagne sans répondre.")
    return create(s, name or f"Sans réponse · {camp.name}", ids, source="campaign")


def counts(s: Session, list_ids) -> dict[int, int]:
    ids = list(list_ids)
    if not ids:
        return {}
    return dict(s.execute(select(ContactListMember.list_id, func.count()).where(ContactListMember.list_id.in_(ids))
                          .group_by(ContactListMember.list_id)).all())


def to_json(s: Session, cl: ContactList, n: int | None = None, names: dict | None = None) -> dict:
    if n is None:
        n = counts(s, [cl.id]).get(cl.id, 0)
    if names is None:
        u = s.get(AppUser, cl.owner_id) if cl.owner_id else None
        owner = (u.full_name or u.email) if u else None
    else:
        owner = names.get(cl.owner_id)
    by = None
    if cl.assigned_by:
        if names is not None:
            by = names.get(cl.assigned_by)
        elif (u2 := s.get(AppUser, cl.assigned_by)) is not None:
            by = u2.full_name or u2.email
    return {"id": cl.id, "name": cl.name, "count": n, "source": cl.source, "shared": cl.shared, "lot": cl.lot_number,
            "assigned_by": by, "assigned_at": cl.assigned_at.isoformat() if cl.assigned_at else None,
            "assigned_by_me": cl.assigned_by is not None and cl.assigned_by == user_id() and cl.owner_id != user_id(),
            "owner": owner, "mine": cl.owner_id is not None and cl.owner_id == user_id(),
            "editable": can_edit(cl), "created_at": cl.created_at.isoformat() if cl.created_at else None,
            "updated_at": cl.updated_at.isoformat() if cl.updated_at else None}


def listing(s: Session) -> list[dict]:
    rows = list(s.scalars(select(ContactList).order_by(ContactList.updated_at.desc(), ContactList.id.desc())))
    n = counts(s, [r.id for r in rows])
    names = {u.id: (u.full_name or u.email) for u in s.scalars(select(AppUser).execution_options(oddo_all=True))}
    return [to_json(s, r, n.get(r.id, 0), names) for r in rows]


def lists_of(s: Session, contact_id: int) -> list[dict]:
    """Les listes (visibles) où figure ce contact, pour sa fiche."""
    rows = s.execute(select(ContactList.id, ContactList.name).join(
        ContactListMember, ContactListMember.list_id == ContactList.id).where(ContactListMember.contact_id == contact_id)
        .order_by(ContactList.name)).all()
    return [{"id": i, "name": n} for i, n in rows]


# --------------------------------------------------------------------------- V3.7 : lots numérotés

def next_lot(s: Session) -> int:
    """Numéro du prochain lot, pour toute l'équipe (1, 2, 3…)."""
    top = s.scalar(select(func.max(ContactList.lot_number)).execution_options(oddo_all=True))
    return (top or 0) + 1


def stamp_lot(s: Session, cl: ContactList, new_ids) -> int | None:
    """Un import ou une recherche crée un lot : la liste reçoit le numéro suivant, et ses NOUVEAUX
    contacts le prennent (un contact déjà connu garde son lot d'origine, donc les mêmes textes)."""
    ids = [int(i) for i in new_ids or ()]
    if not ids:
        return cl.lot_number
    if cl.lot_number is None:
        cl.lot_number = next_lot(s)
    for c in s.scalars(select(Contact).where(Contact.id.in_(ids), Contact.lot_number.is_(None))):
        c.lot_number = cl.lot_number
    return cl.lot_number


# --------------------------------------------------------------------------- V3.8 : confier une liste

def colleagues(s: Session) -> list[dict]:
    """Collègues actifs à qui confier une liste (sans soi-même), avec ou sans boîte mail branchée."""
    from app.models import Mailbox
    me = user_id()
    has_box = set(s.scalars(select(Mailbox.user_id).where(Mailbox.user_id.is_not(None)).execution_options(oddo_all=True)))
    rows = s.scalars(select(AppUser).where(AppUser.active.is_(True)).order_by(AppUser.full_name, AppUser.email)
                     .execution_options(oddo_all=True))
    return [{"id": u.id, "name": u.full_name or u.email, "email": u.email, "has_mailbox": u.id in has_box}
            for u in rows if u.id != me]


def assign(s: Session, cl: ContactList, target_id: int, note: str | None = None) -> AppUser:
    """Confie la liste : le collègue en devient propriétaire (il lance la campagne depuis SA boîte) ;
    celui qui confie la garde en vue. Il est prévenu par sa cloche (et par email si demandé)."""
    if not can_edit(cl):
        raise ListError("Seul le propriétaire de la liste (ou l'administrateur) peut la confier.")
    u = s.get(AppUser, target_id)
    if u is None or not u.active:
        raise ListError("Collègue introuvable ou désactivé.")
    if u.id == cl.owner_id:
        raise ListError(f"La liste est déjà à {u.full_name or u.email}.")
    cl.assigned_by = user_id() if user_id() is not None else cl.owner_id
    cl.owner_id = u.id
    cl.assigned_at = utcnow()
    cl.assign_note = (note or "").strip()[:2000] or None
    return u


def assigned_to_me(s: Session, since) -> list[ContactList]:
    """Listes que l'on m'a confiées récemment et pour lesquelles je n'ai pas encore lancé de campagne."""
    from app.models import Campaign
    me = user_id()
    if me is None:
        return []
    rows = list(s.scalars(select(ContactList).where(ContactList.owner_id == me, ContactList.assigned_by.is_not(None),
                                                    ContactList.assigned_at >= since)))
    if not rows:
        return []
    used = {str((c.filters or {}).get("list_id")) for c in s.scalars(select(Campaign)) if (c.filters or {}).get("list_id")}
    return [r for r in rows if str(r.id) not in used]

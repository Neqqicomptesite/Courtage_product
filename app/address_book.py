"""V3.7 : suggestions d'adresses pendant la saisie (À, Cc, Cci), comme Gmail.

Sources, fusionnées par adresse :
- le carnet appris de l'employé : chaque adresse à qui il écrit depuis l'appli (+1 à chaque fois)
  et chaque expéditeur vu dans sa boîte (nom gardé) ;
- les contacts de l'appli (prospects, compagnies, clients), avec nom et entreprise ;
- les collègues (comptes de l'équipe).
Le carnet est propre à chaque employé ; en poste unique, user_id est vide.
"""
from __future__ import annotations

import re
import unicodedata
from datetime import datetime

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.importer import EMAIL_RE
from app.timeutil import utcnow

MAX_NAME = 200


def _uid():
    from app.current import user_id
    return user_id()


def _fold(s: str) -> str:
    return unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()


def _owner(q, model, uid):
    return q.where(model.user_id.is_(None) if uid is None else model.user_id == uid)


def _upsert(s: Session, email: str, name: str | None, used: bool, when: datetime, uid) -> None:
    from app.models import AddressBook
    email = (email or "").strip().lower()
    if not EMAIL_RE.match(email):
        return
    row = s.scalars(_owner(select(AddressBook).where(AddressBook.email == email), AddressBook, uid)).first()
    if row is None:
        row = AddressBook(user_id=uid, email=email, uses=0)
        s.add(row)
    clean = (name or "").strip().strip('"').strip()
    if clean and clean.lower() != email and (not row.name or not used):
        row.name = clean[:MAX_NAME]
    if used:
        row.uses = (row.uses or 0) + 1
        row.last_used = when
    else:
        row.last_seen = when


def record_sent(s: Session, addresses: list[str], when: datetime | None = None) -> None:
    """Adresses à qui l'employé vient d'écrire (À, Cc, Cci)."""
    when, uid = when or utcnow(), _uid()
    for a in dict.fromkeys(addresses):
        _upsert(s, a, None, True, when, uid)


def record_seen(people: list[tuple[str, str]], own: set[str] | None = None) -> None:
    """Expéditeurs vus dans la boîte (nom, adresse) : seulement les nouveaux, sans écriture inutile."""
    from app.db import get_session
    from app.models import AddressBook
    uid, own = _uid(), {o.lower() for o in own or ()}
    people = [(n, a.lower()) for n, a in people if a and a.lower() not in own]
    if not people:
        return
    with get_session() as s:
        known = set(s.scalars(_owner(select(AddressBook.email).where(AddressBook.email.in_({a for _, a in people})),
                                     AddressBook, uid)))
        fresh = {a: n for n, a in people if a not in known}
        if not fresh:
            return
        now = utcnow()
        for a, n in fresh.items():
            _upsert(s, a, n, False, now, uid)
        s.commit()


def suggest(s: Session, q: str, limit: int = 8, exclude: list[str] | None = None) -> list[dict]:
    from app.models import AddressBook, AppUser, Contact
    q = (q or "").strip().lower()
    if len(q) < 2:
        return []
    exclude = {e.lower() for e in exclude or ()}
    like = f"%{q}%"
    out: dict[str, dict] = {}

    def add(email, name, company=None, kind=None, uses=0, last=None, contact_id=None):
        email = (email or "").lower()
        if not email or email in exclude:
            return
        cur = out.setdefault(email, {"email": email, "name": None, "company": None, "kind": None, "uses": 0,
                                     "last": None, "contact_id": None})
        cur["name"] = cur["name"] or (name or None)
        cur["company"] = cur["company"] or company
        cur["kind"] = cur["kind"] or kind
        cur["uses"] += uses or 0
        cur["contact_id"] = cur["contact_id"] or contact_id
        if last and (cur["last"] is None or last > cur["last"]):
            cur["last"] = last

    book = _owner(select(AddressBook).where(or_(AddressBook.email.like(like), func.lower(AddressBook.name).like(like))),
                  AddressBook, _uid())
    for r in s.scalars(book.order_by(AddressBook.uses.desc()).limit(40)):
        add(r.email, r.name, uses=r.uses, last=r.last_used or r.last_seen)
    full = func.lower(func.coalesce(Contact.first_name, "") + " " + func.coalesce(Contact.last_name, ""))
    cq = select(Contact).where(or_(Contact.email.like(like), full.like(like), func.lower(Contact.company).like(like)))
    for c in s.scalars(cq.limit(40)):
        name = " ".join(x for x in (c.first_name, c.last_name) if x) or None
        add(c.email, name, c.company, c.kind, contact_id=c.id)
    uq = select(AppUser).where(AppUser.active.is_(True),
                               or_(AppUser.email.like(like), func.lower(AppUser.full_name).like(like)))
    for u in s.scalars(uq.execution_options(oddo_all=True).limit(10)):
        add(u.email, u.full_name or None, kind="team")

    fq = _fold(q)

    def score(x: dict) -> tuple:
        local = x["email"].split("@")[0]
        words = re.split(r"[\s.\-_'@]+", _fold(f"{x['name'] or ''} {x['email']}"))
        starts = local.startswith(q) or any(w.startswith(fq) for w in words if w)
        return (starts, x["uses"], x["last"] is not None and x["last"].timestamp(), bool(x["contact_id"]))

    ranked = sorted(out.values(), key=score, reverse=True)[:limit]
    for x in ranked:
        x["last"] = x["last"].isoformat() if x["last"] else None
    return ranked

"""V3 : l'utilisateur « en cours » (plusieurs employés sur le même serveur).

Le serveur web le fixe pour chaque requête (après vérification de la connexion) ; le moteur
d'envoi et la synchronisation IMAP le fixent tour à tour pour chaque employé. Tout le reste
du code (boîte mail, réglages, campagnes…) lit `user_id()` pour ne travailler que sur les
données de cette personne.

Sans utilisateur (poste unique V2, tests d'avant la V3) : None, et tout marche comme avant.
"""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from typing import Iterator

_user: ContextVar[int | None] = ContextVar("oddo_user", default=None)
_role: ContextVar[str | None] = ContextVar("oddo_role", default=None)


def user_id() -> int | None:
    return _user.get()


def org_id() -> int:
    """Cabinet « en cours ». Un seul cabinet pour l'instant (n° 1) : toutes les nouvelles tables
    portent déjà cette colonne pour que l'ouverture à plusieurs cabinets reste simple
    (voir « Règles en attendant plusieurs cabinets » dans le README)."""
    return 1


def is_admin() -> bool:
    """Sans employé en cours : vrai en poste unique (une seule personne) ; FAUX sur le serveur
    (refus par défaut : une future adresse hors connexion ne serait pas « admin »)."""
    if _user.get() is None:
        from app.paths import is_server_mode
        return not is_server_mode()
    return _role.get() == "admin"


@contextmanager
def as_user(uid: int | None, role: str | None = "user") -> Iterator[None]:
    t1, t2 = _user.set(uid), _role.set(role)
    try:
        yield
    finally:
        _user.reset(t1)
        _role.reset(t2)

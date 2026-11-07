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


def is_admin() -> bool:
    return _user.get() is None or _role.get() == "admin"


@contextmanager
def as_user(uid: int | None, role: str | None = "user") -> Iterator[None]:
    t1, t2 = _user.set(uid), _role.set(role)
    try:
        yield
    finally:
        _user.reset(t1)
        _role.reset(t2)

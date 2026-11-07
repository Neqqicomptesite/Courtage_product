"""Petits outils partagés par les modules d'API V2."""
from __future__ import annotations

from datetime import date, datetime
from typing import Any

from fastapi import HTTPException

from app.models import Contact


def iso(dt: datetime | date | None) -> str | None:
    return dt.isoformat() if dt else None


def contact_ref(c: Contact | None) -> dict | None:
    if c is None:
        return None
    return {"id": c.id, "first_name": c.first_name, "last_name": c.last_name, "email": c.email,
            "company": c.company, "sequence_code": c.sequence_code, "phone": c.phone}


def not_found(what: str = "Élément") -> HTTPException:
    return HTTPException(404, f"{what} introuvable.")


class FormLike:
    """Fait passer un corps JSON pour un formulaire HTML (méthodes get / getlist).

    Les fonctions de validation de la V1 (app/web/forms.py, routes_settings.read_sending_form)
    lisent des formulaires : grâce à cet adaptateur, l'API V2 les réutilise telles quelles,
    sans dupliquer les règles. Les booléens deviennent « on » comme une case cochée.
    """

    def __init__(self, data: dict[str, Any]):
        self.data = data

    def _s(self, v: Any) -> str:
        if v is True:
            return "on"
        if v is False or v is None:
            return ""
        return str(v)

    def get(self, key: str, default: Any = None) -> Any:
        if key not in self.data:
            return default
        v = self.data[key]
        return self._s(v) if not isinstance(v, list) else (self._s(v[0]) if v else default)

    def getlist(self, key: str) -> list[str]:
        v = self.data.get(key)
        if v is None:
            return []
        return [self._s(x) for x in v] if isinstance(v, list) else [self._s(v)]

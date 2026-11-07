"""Liste d'exclusion : emails ou domaines à ne JAMAIS contacter.

Trois formes d'entrée dans la table `suppression` :
- « jean@exemple.ma »        : une adresse précise ;
- « @exemple.ma »            : tout un domaine ;
- « sha256:3f2a… »           : empreinte d'une adresse dont les données ont été
                               effacées (droit d'effacement, §9). On ne garde pas
                               l'adresse, seulement de quoi la reconnaître si elle revient.

Note d'honnêteté : une empreinte d'email n'est pas une anonymisation parfaite
(quelqu'un qui devine l'adresse peut vérifier l'empreinte). C'est le compromis
demandé par le §9 : effacer les données tout en garantissant de ne jamais recontacter.
"""
import hashlib

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Suppression

HASH_PREFIX = "sha256:"


def email_hash(email: str) -> str:
    return HASH_PREFIX + hashlib.sha256(email.strip().lower().encode("utf-8")).hexdigest()


def domain_of(email: str) -> str:
    return email.rsplit("@", 1)[-1].lower()


def normalize_entry(raw: str) -> str | None:
    """« Exemple.MA », « @exemple.ma » -> « @exemple.ma » ; une adresse -> en minuscules."""
    value = raw.strip().lower()
    if not value:
        return None
    if "@" in value and not value.startswith("@"):
        local, _, dom = value.partition("@")
        return value if local and "." in dom else None
    dom = value.lstrip("@")
    return f"@{dom}" if "." in dom and " " not in dom else None


def suppressed_keys(session: Session) -> set[str]:
    return set(session.scalars(select(Suppression.email_or_domain)))


def is_suppressed(email: str, keys: set[str]) -> bool:
    """`keys` vient de suppressed_keys() : on le charge une fois pour tout un import."""
    e = email.strip().lower()
    return e in keys or f"@{domain_of(e)}" in keys or email_hash(e) in keys


def is_suppressed_db(session: Session, email: str) -> bool:
    e = email.strip().lower()
    candidates = [e, f"@{domain_of(e)}", email_hash(e)]
    return session.scalars(
        select(Suppression.id).where(Suppression.email_or_domain.in_(candidates))
    ).first() is not None


def add(session: Session, entry: str, reason: str) -> bool:
    """Ajoute une entrée (déjà normalisée). Renvoie False si elle existait déjà."""
    exists = session.scalars(select(Suppression).where(Suppression.email_or_domain == entry)).first()
    if exists:
        return False
    session.add(Suppression(email_or_domain=entry, reason=reason))
    return True

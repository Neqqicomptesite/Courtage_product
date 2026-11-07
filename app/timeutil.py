"""Gestion du temps.

Règle d'or du projet : en base, TOUT est en UTC. On ne convertit en heure du
Maroc qu'au moment d'afficher, ou pour décider « est-on dans la fenêtre
d'envoi ? ». L'écart UTC n'est jamais écrit en dur : il vient de la base IANA
(paquet tzdata), qui connaît les changements d'heure du Maroc (Ramadan, etc.).
"""
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

TZ_NAME = "Africa/Casablanca"
TZ = ZoneInfo(TZ_NAME)


def utcnow() -> datetime:
    """Heure actuelle en UTC, « aware » (avec fuseau). Ne jamais utiliser datetime.now() seul."""
    return datetime.now(timezone.utc)


def to_local(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        raise ValueError("datetime sans fuseau : impossible de savoir ce qu'il représente")
    return dt.astimezone(TZ)


def fmt_local(dt: datetime | None, fmt: str = "%d/%m/%Y %H:%M") -> str:
    """Affichage en heure du Maroc. Utilisé comme filtre Jinja `|local`."""
    if dt is None:
        return "—"
    return to_local(dt).strftime(fmt)


JOURS = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]


def fmt_local_long(dt: datetime | None) -> str:
    """« mardi 03/11/2026 à 09:00 » (indépendant de la langue de Windows)."""
    if dt is None:
        return "—"
    loc = to_local(dt)
    return f"{JOURS[loc.weekday()]} {loc:%d/%m/%Y} à {loc:%H:%M}"

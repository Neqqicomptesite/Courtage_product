"""V3.11.2 (13/11) : protéger la réputation d'envoi du domaine.

Le 13/11, l'hébergeur a jeté des emails : « Domain oddo.ma has exceeded the max defers and failures per
hour (16/10 (25%)) allowed. Message discarded. » Au-delà d'environ 25 % d'échecs dans l'heure, il bloque
TOUT le domaine (même les emails vers de bonnes adresses, même ceux écrits à la main).

- Disjoncteur : dès 3 rebonds reçus dans l'heure, le moteur se met en pause une heure (reprise seule).
- Avis de l'hébergeur (limite atteinte) : pause d'une heure, le contact n'est pas marqué en rebond et
  l'email jeté est renvoyé après la pause.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import settings_store
from app.models import EventLog, Message
from app.timeutil import to_local

PAUSE = timedelta(hours=1)
BOUNCES_PER_HOUR = 3


def _iso(dt: datetime) -> str:
    return dt.isoformat()


def paused_until(s: Session) -> datetime | None:
    v = settings_store.get(s, "engine_paused_until")
    try:
        return datetime.fromisoformat(v) if v else None
    except (TypeError, ValueError):
        return None


def pause(s: Session, until: datetime, reason: str) -> None:
    cur = paused_until(s)
    if cur and cur >= until:
        return
    settings_store.set_(s, "engine_paused_until", _iso(until))
    text = f"{reason} Reprise automatique à {to_local(until):%H:%M}."
    settings_store.set_(s, "engine_last_error", text)
    s.add(EventLog(level="warning", entity="engine", text=f"Envois en pause : {text}"))


def check(s: Session, now: datetime) -> str | None:
    """Raison de ne pas envoyer maintenant, ou None."""
    until = paused_until(s)
    if until and now < until:
        return f"Envois en pause jusqu'à {to_local(until):%H:%M} (protection du domaine)"
    since = now - PAUSE
    q = select(func.count(Message.id), func.max(Message.received_at)).where(
        Message.direction == "in", Message.kind.in_(("bounce_hard", "bounce_soft")),
        Message.test_mode.is_(False), Message.received_at >= since)
    n, last = s.execute(q.execution_options(oddo_all=True)).one()
    if n and n >= BOUNCES_PER_HOUR and last is not None:
        end = max(now, last) + PAUSE
        pause(s, end, f"{n} emails ont rebondi dans l'heure : l'hébergeur bloque le domaine au-delà d'environ "
                      "25 % d'échecs, l'appli s'arrête avant.")
        return f"Envois en pause jusqu'à {to_local(end):%H:%M} ({n} rebonds dans l'heure)"
    return None

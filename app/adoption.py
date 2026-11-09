"""Suivi de la prise en main par l'équipe (V3.3.5), pour l'administrateur (page Équipe).

Pour chaque employé : les 5 étapes de « Bien démarrer » (celles que chacun voit déjà sur son
tableau de bord), puis 4 étapes d'usage réel (premier email réel, première campagne, première
réponse classée, premier dossier de cotation), et son activité des 7 derniers jours.

Rien de nouveau n'est enregistré : tout se déduit de ce que l'appli stocke déjà. Les chiffres
d'un employé sont lus « en son nom » (app.current.as_user) : le filtre de app/scope.py ne garde
que sa boîte, ses campagnes, ses réglages…
"""
from __future__ import annotations

from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import AppUser, Campaign, Message, QuoteCase
from app.timeutil import utcnow

SETUP = [("mailbox", "Boîte mail branchée"), ("signature", "Signature"), ("test", "Essai en mode test"),
         ("contacts", "Prospects dans la base"), ("real", "Passé en mode réel")]
USAGE = [("real_send", "Premier email réel"), ("campaign", "Première campagne"),
         ("classified", "Première réponse classée"), ("quote", "Premier dossier de cotation")]
STEPS = SETUP + USAGE


def _count(s: Session, stmt) -> int:
    return s.scalar(stmt) or 0


def for_current_user(s: Session, uid: int | None) -> dict:
    """Étapes et activité de l'employé en cours (appeler sous as_user(uid) en mode serveur)."""
    from app import settings_store, stats
    from app.web.api_v28 import guide_progress
    week = utcnow() - timedelta(days=7)
    setup = guide_progress(s)["steps"]
    sent = select(func.count(Message.id)).where(Message.direction == "out", Message.sent_at.is_not(None))
    quotes = select(func.count(QuoteCase.id))
    if uid is not None:
        quotes = quotes.where(QuoteCase.owner_id == uid)
    usage = {
        "real_send": _count(s, sent.where(Message.test_mode.is_(False))) > 0,
        "campaign": _count(s, select(func.count(Campaign.id)).where(
            Campaign.direct.is_(False), Campaign.activated_at.is_not(None))) > 0,
        "classified": _count(s, select(func.count(Message.id)).where(
            Message.direction == "in", Message.classification.is_not(None))) > 0,
        "quote": _count(s, quotes) > 0,
    }
    done = {**{k: bool(setup.get(k)) for k, _ in SETUP}, **usage}
    activity = {
        "sent_real_7d": _count(s, sent.where(Message.test_mode.is_(False), Message.sent_at >= week)),
        "sent_test_7d": _count(s, sent.where(Message.test_mode.is_(True), Message.sent_at >= week)),
        "replies_7d": _count(s, select(func.count(Message.id)).where(
            Message.direction == "in", Message.kind.in_(("reply", "unsubscribe")), Message.received_at >= week)),
        "to_classify": stats.unclassified_count(s),
        "active_campaigns": _count(s, select(func.count(Campaign.id)).where(
            Campaign.direct.is_(False), Campaign.status == "active")),
        "open_quotes": _count(s, quotes.where(QuoteCase.stage.notin_(("won", "lost")))),
    }
    return {"steps": done, "done": sum(done.values()), "total": len(STEPS),
            "test_mode": bool(settings_store.get(s, "test_mode")), "activity": activity}


def level(u: AppUser, data: dict, now=None) -> tuple[str, str]:
    """Où en est l'employé, en quelques mots, et ce que l'administrateur peut faire."""
    now = now or utcnow()
    if not u.auth_id:
        return "invited", "N'a pas encore accepté l'invitation : renvoyez-lui le lien"
    if u.last_seen_at is None or now - u.last_seen_at > timedelta(days=5):
        return "idle", "Pas venu depuis plus de 5 jours : faites un point avec lui"
    if not data["steps"]["mailbox"]:
        return "setup", "Boîte mail pas encore branchée : aidez-le à la régler"
    if data["test_mode"]:
        return "testing", "Encore en mode test : relisez un essai ensemble, puis passage en réel"
    if data["activity"]["sent_real_7d"] == 0 and data["activity"]["active_campaigns"] == 0:
        return "quiet", "En mode réel, mais rien envoyé cette semaine"
    return "active", "Utilise l'appli"


def team(s: Session) -> list[dict]:
    """Tous les employés actifs, chacun lu en son nom (administrateur, mode serveur)."""
    from app.current import as_user
    now = utcnow()
    out = []
    for u in s.scalars(select(AppUser).where(AppUser.active.is_(True))
                       .order_by(AppUser.full_name, AppUser.email)).all():
        with as_user(u.id, u.role):
            data = for_current_user(s, u.id)
        code, label = level(u, data, now)
        out.append({"id": u.id, "name": u.full_name or u.email, "email": u.email,
                    "last_seen_at": u.last_seen_at.isoformat() if u.last_seen_at else None,
                    "level": code, "level_label": label, **data})
    return out

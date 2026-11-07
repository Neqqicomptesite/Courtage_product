"""« À répondre » (V2.12) : les emails reçus auxquels Omar n'a pas répondu depuis N jours ouvrés,
le pendant de « Envoyés sans réponse ».

On lit la boîte de réception et le dossier « Envoyés » (en lecture seule, comme la page Boîte mail)
sur les 30 derniers jours. Un email reçu compte comme « répondu » si un email envoyé APRÈS lui :
- répond dans le même fil (In-Reply-To / References contient son Message-ID), ou
- est adressé à son expéditeur.

Sont écartés : newsletters et envois automatiques (en-têtes List-Unsubscribe, List-Id,
Precedence: bulk, Auto-Submitted), adresses « noreply / notification / mailer-daemon… »,
réponses d'absence, et les emails venant d'Omar lui-même. Un contact connu est toujours gardé
(sauf envoi automatique). Une seule ligne par expéditeur : son email le plus récent sans réponse.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone

from sqlalchemy import select

from app import mailbox_browser, scheduling, settings_store
from app.db import get_session
from app.mailbox_service import get_primary
from app.models import Contact
from app.timeutil import to_local

AUTO_SENDER = re.compile(r"(no-?reply|ne-?pas-?repondre|donotreply|notification|notifications|mailer-daemon|postmaster|"
                         r"newsletter|news@|bounce|alert|digest|support@|billing|invoice|receipts?@|statements?)", re.I)
AUTO_SUBJECT = re.compile(r"^\s*(automatic reply|réponse automatique|reponse automatique|out of office|absence|"
                          r"undeliverable|non remis|delivery status|accusé de réception)", re.I)
WINDOW_DAYS = 30


def business_days_since(when: datetime, now: datetime, window) -> int:
    d, today, n = to_local(when).date(), to_local(now).date(), 0
    while d < today:
        d = d.fromordinal(d.toordinal() + 1)
        n += window.is_business_day(d)
    return n


def _parse(iso: str | None) -> datetime | None:
    if not iso:
        return None
    try:
        dt = datetime.fromisoformat(iso)
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def awaiting(now: datetime | None = None, refresh: bool = False, imap_factory=None) -> dict:
    """Peut lever mailbox_browser.MailboxUnavailable (boîte non configurée ou injoignable)."""
    now = now or datetime.now(timezone.utc)
    with get_session() as s:
        days = int(settings_store.get(s, "followup_days") or 3)
        window = scheduling.SendWindow.from_settings(s)
        mb = get_primary(s)
        me = (mb.email if mb else "").lower()
        sent_folder = mb.sent_folder if mb else None
        contacts = {c.email.lower(): c for c in s.scalars(select(Contact))}
        dismissed = {k: _parse(v) for k, v in (settings_store.get(s, "awaiting_dismissed") or {}).items()}
        refs_contacts = {e: {"id": c.id, "first_name": c.first_name, "last_name": c.last_name, "email": c.email,
                             "company": c.company, "kind": c.kind} for e, c in contacts.items()}

    inbox = mailbox_browser.list_messages("INBOX", WINDOW_DAYS, refresh, now, imap_factory)["items"]
    sent = mailbox_browser.list_messages(sent_folder, WINDOW_DAYS, refresh, now, imap_factory)["items"] if sent_folder else []

    replied_ids: set[str] = set()
    last_sent_to: dict[str, datetime] = {}
    for m in sent:
        when = _parse(m["date"])
        replied_ids.update(m.get("refs") or [])
        for a in m.get("to") or []:
            if when and (a not in last_sent_to or when > last_sent_to[a]):
                last_sent_to[a] = when

    best: dict[str, dict] = {}
    for m in inbox:
        sender = m["from_email"]
        when = _parse(m["date"])
        if not sender or not when or sender == me:
            continue
        known = sender in contacts
        automated = m.get("bulk") or AUTO_SUBJECT.search(m["subject"] or "")
        if automated or (not known and AUTO_SENDER.search(sender)):
            continue
        if m.get("message_id") and m["message_id"] in replied_ids:
            continue
        if sender in dismissed and dismissed[sender] and when <= dismissed[sender]:
            continue  # rangé à la main (V2.13) : revient seulement si un nouvel email arrive
        if sender in last_sent_to and last_sent_to[sender] > when:
            continue
        bd = business_days_since(when, now, window)
        if bd < days:
            continue
        if sender not in best or when > _parse(best[sender]["date"]):
            best[sender] = {"uid": m["uid"], "folder": "INBOX", "from_name": m["from_name"], "from_email": sender,
                            "to": m.get("to") or [], "subject": m["subject"], "date": m["date"], "business_days": bd,
                            "seen": m.get("seen", True), "message_id": m.get("message_id"), "size": m.get("size"),
                            "has_attachments": m.get("has_attachments", False),
                            "contact": refs_contacts.get(sender)}
    items = sorted(best.values(), key=lambda x: x["date"] or "")
    return {"days": days, "items": items, "window_days": WINDOW_DAYS, "fetched_at": now.isoformat(),
            "sent_folder": sent_folder}


def dismiss(items: list[dict]) -> int:
    """V2.13 : « Marquer comme répondu » : l'expéditeur sort de la liste jusqu'à son prochain email."""
    with get_session() as s:
        d = dict(settings_store.get(s, "awaiting_dismissed") or {})
        for it in items:
            sender, when = (it.get("from_email") or "").lower(), _parse(it.get("date"))
            if sender and when and (sender not in d or _parse(d[sender]) is None or when > _parse(d[sender])):
                d[sender] = when.isoformat()
        if len(d) > 3000:  # on garde les plus récents
            d = dict(sorted(d.items(), key=lambda kv: kv[1])[-3000:])
        settings_store.set_(s, "awaiting_dismissed", d)
        s.commit()
        return len(items)


def restore(senders: list[str]) -> None:
    """Annuler « Marquer comme répondu »."""
    with get_session() as s:
        d = dict(settings_store.get(s, "awaiting_dismissed") or {})
        for e in senders:
            d.pop((e or "").lower(), None)
        settings_store.set_(s, "awaiting_dismissed", d)
        s.commit()

"""Analyse des emails reçus : quel type de message, et à quel envoi il répond (§6.7).

Uniquement des règles fixes et lisibles (pas d'IA) : on doit pouvoir expliquer
pourquoi un message a été classé ainsi. En cas de doute, on classe « réponse »,
car c'est le choix le plus sûr : il arrête les relances et Omar voit le message.

Ce module ne touche pas à la base : il reçoit des octets, il rend une analyse.
"""
from __future__ import annotations

import html
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email import message_from_bytes, policy
from email.message import EmailMessage
from email.utils import getaddresses, parseaddr, parsedate_to_datetime

FREE_MAIL_DOMAINS = {
    "gmail.com", "googlemail.com", "yahoo.com", "yahoo.fr", "ymail.com", "icloud.com", "me.com",
    "aol.com", "gmx.com", "gmx.fr", "proton.me", "protonmail.com", "menara.ma",
}
FREE_MAIL_PREFIXES = ("hotmail.", "outlook.", "live.", "msn.", "yahoo.")

REPLY_PREFIX_RE = re.compile(r"^\s*(re|aw|sv|antw|rif)\s*(\[\d+\])?\s*:")
AUTO_SUBJECT_WORDS = ["absence", "absent", "out of office", "reponse automatique", "automatic reply",
                      "conge", "auto-reply", "autoreply", "abwesenheit"]
# Formes « repliées » (minuscules, sans accents). Recherchées seulement dans un message TRÈS
# court : « faisons un stop sur ce dossier… » dans une vraie réponse ne doit pas désinscrire.
UNSUBSCRIBE_WORDS = ["stop", "desinscri", "desabonn", "unsubscribe", "plus recevoir", "retirez moi",
                     "retirer de votre liste", "plus etre contacte", "remove me"]


def is_free_mail(domain: str) -> bool:
    d = domain.lower()
    return d in FREE_MAIL_DOMAINS or d.startswith(FREE_MAIL_PREFIXES)


def fold(text: str) -> str:
    """Minuscules sans accents : « Réponse » -> « reponse »."""
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()


# ------------------------------------------------------------------ texte

class _HTMLToText:
    BLOCK = re.compile(r"(?i)<\s*(br|/p|/div|/li|/tr|/h\d)\b[^>]*>")

    @classmethod
    def convert(cls, raw: str) -> str:
        raw = re.sub(r"(?is)<(script|style|head)\b.*?</\1>", "", raw)
        # Les citations Outlook / Gmail en HTML : on marque le début pour pouvoir couper.
        raw = re.sub(r"(?i)<blockquote\b[^>]*>", "\n>>>CITATION\n", raw)
        raw = cls.BLOCK.sub("\n", raw)
        raw = re.sub(r"<[^>]+>", "", raw)
        text = html.unescape(raw).replace("\xa0", " ")
        return re.sub(r"\n{3,}", "\n\n", "\n".join(l.rstrip() for l in text.splitlines())).strip()


def body_text(msg: EmailMessage) -> str:
    """Texte lisible : partie text/plain, sinon HTML converti."""
    part = msg.get_body(preferencelist=("plain", "html"))
    if part is None:
        return ""
    try:
        content = part.get_content()
    except (LookupError, UnicodeDecodeError):
        payload = part.get_payload(decode=True) or b""
        content = payload.decode("utf-8", "replace")
    if part.get_content_type() == "text/html":
        content = _HTMLToText.convert(content)
    return content.replace("\r\n", "\n").strip()


_SEPARATORS = re.compile(
    r"^\s*(>>>CITATION|-{2,}\s*(Original Message|Message d'origine|Message original)\s*-{2,}|_{10,})\s*$", re.I)
_FROM_HEADER = re.compile(r"^\s*(De|From)\s*:\s.+", re.I)
# Deux-points obligatoires : « Le client a écrit hier » ne doit pas couper le message.
_WROTE = re.compile(r"^\s*(Le\s.+a\s+écrit|On\s.+wrote)\s*:\s*$", re.I)


def _looks_like_header_block(lines: list[str], i: int) -> bool:
    nxt = " ".join(lines[i + 1:i + 4]).lower()
    return any(k in nxt for k in ("envoyé :", "envoye :", "sent:", "date :", "date:", "à :", "to:",
                                  "objet :", "subject:"))


def strip_quote(text: str) -> str:
    """Retire la citation : lignes « > », puis tout ce qui suit « Le … a écrit : »
    (sur une ou deux lignes), « On … wrote: », un séparateur ou un en-tête de transfert Outlook."""
    lines = text.splitlines()
    out: list[str] = []
    for i, line in enumerate(lines):
        nxt = lines[i + 1] if i + 1 < len(lines) else ""
        if _SEPARATORS.match(line) or _WROTE.match(line):
            break
        if re.match(r"^\s*(Le|On)\s", line, re.I) and _WROTE.match(f"{line} {nxt}"):
            break  # « Le mar. 3 nov. 2026 à 10:00, Omar <…> » / « a écrit : » sur 2 lignes
        if _FROM_HEADER.match(line) and _looks_like_header_block(lines, i):
            break
        if line.lstrip().startswith(">"):
            continue
        out.append(line)
    return "\n".join(out).strip()


# ------------------------------------------------------------- rebonds (DSN)

@dataclass
class BounceInfo:
    hard: bool
    status: str
    recipient: str | None
    original_message_id: str | None


_STATUS_RE = re.compile(r"\b([245])\.(\d{1,3})\.(\d{1,3})\b")
_MSGID_RE = re.compile(r"Message-ID:\s*(<[^>\s]+>)", re.I)


def _is_bounce(msg: EmailMessage, sender: str) -> bool:
    s = sender.lower()
    if "mailer-daemon" in s or "postmaster" in s:
        return True
    return msg.get_content_type() == "multipart/report" and \
        (msg.get_param("report-type") or "").lower() == "delivery-status"


def parse_bounce(msg: EmailMessage) -> BounceInfo:
    status = recipient = original_id = None
    for part in msg.walk():
        ctype = part.get_content_type()
        if ctype == "message/delivery-status":
            # Le contenu est une suite de blocs d'en-têtes (par message, puis par destinataire).
            raw = part.as_string()
            m = re.search(r"^Status:\s*([245]\.\d{1,3}\.\d{1,3})", raw, re.M | re.I)
            status = status or (m.group(1) if m else None)
            m = re.search(r"^Final-Recipient:\s*(?:rfc822;)?\s*<?([^\s>]+@[^\s>]+)>?", raw, re.M | re.I)
            recipient = recipient or (m.group(1).lower() if m else None)
        elif ctype in ("message/rfc822", "text/rfc822-headers"):
            raw = part.as_string()
            m = _MSGID_RE.search(raw)
            original_id = original_id or (m.group(1) if m else None)
    if status is None or original_id is None:
        # Rebond « texte libre » (sans rapport structuré) : on cherche dans le corps.
        text = msg.as_string()
        if status is None:
            m = _STATUS_RE.search(text)
            status = ".".join(m.groups()) if m else None
        if original_id is None:
            ids = _MSGID_RE.findall(text)
            original_id = ids[-1] if ids else None
    # Sans code lisible, on considère le rebond comme TEMPORAIRE : on n'élimine pas
    # un contact sur une supposition.
    hard = bool(status and status.startswith("5"))
    return BounceInfo(hard, status or "inconnu", recipient, original_id)


# ------------------------------------------------------- réponses automatiques

def _is_auto_reply(msg: EmailMessage) -> bool:
    auto = (msg.get("Auto-Submitted") or "").strip().lower()
    if auto and auto != "no":
        return True
    if msg.get("X-Autoreply") or msg.get("X-Autorespond") or msg.get("X-Autoresponse"):
        return True
    if (msg.get("Precedence") or "").strip().lower() in ("auto_reply", "bulk", "junk"):
        return True
    subject = fold(str(msg.get("Subject") or ""))
    # V3.9.2 : « RE: <votre objet> » est une vraie réponse, même si votre objet contient « congé » ou
    # « absence » (sinon la séquence continuerait). Les vraies réponses automatiques s'annoncent par
    # leurs en-têtes (ci-dessus) ou commencent par « Réponse automatique », « Absent du bureau »…
    if REPLY_PREFIX_RE.match(subject):
        return False
    return any(w in subject for w in AUTO_SUBJECT_WORDS)


_MONTHS = ("janvier|fevrier|février|mars|avril|mai|juin|juillet|aout|août|septembre|octobre|novembre|decembre|décembre|"
           "january|february|march|april|may|june|july|august|september|october|november|december")
_RETURN_RE = re.compile(
    r"(?:retour|rentre|reviens|de retour|back|return|until|jusqu'?au|jusqu’au|à partir du|a partir du)"
    r"[^.\n]{0,40}?(\d{1,2}[/.-]\d{1,2}(?:[/.-]\d{2,4})?|\d{1,2}(?:er)?\s+(?:" + _MONTHS + r")(?:\s+\d{4})?|"
    r"(?:" + _MONTHS + r")\s+\d{1,2}(?:st|nd|rd|th)?(?:,?\s+\d{4})?)", re.I)


def return_date(text: str) -> str | None:
    """Date de retour telle qu'écrite (« 12/11/2026 », « 12 novembre ») : affichée, jamais interprétée."""
    m = _RETURN_RE.search(text)
    return m.group(1) if m else None


# ------------------------------------------------------------- désinscription

def _is_unsubscribe(subject: str, text_without_quote: str) -> bool:
    if fold(subject).strip() in ("stop", "re: stop", "re : stop", "unsubscribe"):
        return True
    words = re.findall(r"[a-z]+", fold(text_without_quote))
    if not words:
        return False
    if words[0] == "stop":
        return True
    joined = " ".join(words)
    # « contient seulement » : un message très court (12 mots au plus) qui contient un des mots-clés
    return len(words) <= 12 and any(w in joined for w in UNSUBSCRIBE_WORDS)


# ---------------------------------------------------------------- analyse

@dataclass
class Analysis:
    kind: str                              # reply | auto_reply | bounce_hard | bounce_soft | unsubscribe
    message_id: str | None
    in_reply_to: str | None
    references: list[str]
    sender: str
    subject: str
    received_at: datetime
    text: str                               # sans citation
    full_text: str
    return_date: str | None = None
    bounce: BounceInfo | None = None
    raw_headers: str = ""
    referenced_ids: list[str] = field(default_factory=list)


def _ids(value: str | None) -> list[str]:
    return re.findall(r"<[^>\s]+>", value or "")


def analyse(raw: bytes) -> Analysis:
    msg: EmailMessage = message_from_bytes(raw, policy=policy.default)
    sender = parseaddr(str(msg.get("From") or ""))[1].lower()
    subject = str(msg.get("Subject") or "").strip()
    try:
        received = parsedate_to_datetime(str(msg.get("Date")))
        if received.tzinfo is None:
            received = received.replace(tzinfo=timezone.utc)
        received = received.astimezone(timezone.utc)
    except (TypeError, ValueError, IndexError):
        received = datetime.now(timezone.utc)
    full = body_text(msg)
    text = strip_quote(full)
    in_reply_to = (_ids(str(msg.get("In-Reply-To") or "")) or [None])[0]
    references = _ids(str(msg.get("References") or ""))
    headers = "\n".join(f"{k}: {v}" for k, v in msg.items())[:4000]
    a = Analysis("reply", (_ids(str(msg.get("Message-ID") or "")) or [None])[0], in_reply_to, references,
                 sender, subject, received, text, full, raw_headers=headers)
    a.referenced_ids = list(dict.fromkeys(([in_reply_to] if in_reply_to else []) + references))

    if _is_bounce(msg, sender):
        a.bounce = parse_bounce(msg)
        a.kind = "bounce_hard" if a.bounce.hard else "bounce_soft"
        if a.bounce.original_message_id:
            a.referenced_ids.append(a.bounce.original_message_id)
    elif _is_auto_reply(msg):
        a.kind = "auto_reply"
        a.return_date = return_date(full)
    elif _is_unsubscribe(subject, text):
        a.kind = "unsubscribe"
    return a


def addresses(value: str) -> list[str]:
    return [a.lower() for _, a in getaddresses([value]) if a]

"""Boîte mail complète (V2.4) : lire n'importe quel dossier, en lecture seule.

Règles, les mêmes que la synchronisation :
- EXAMINE (dossier ouvert en lecture seule) et BODY.PEEK : rien n'est marqué comme lu,
  déplacé ni supprimé sur le serveur ;
- rien n'est écrit sur le disque : la liste (expéditeur, objet, date) est gardée en
  mémoire 60 secondes au plus, le texte d'un email est relu sur le serveur à l'ouverture
  (choix d'Omar : les emails contiennent des données de clients) ; V2.19 : l'email ouvert reste
  2 minutes en mémoire pour afficher ses images et ouvrir ses pièces jointes.
"""
from __future__ import annotations

import imaplib
import logging
import re
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email import message_from_bytes, policy
from email.header import decode_header, make_header
from email.utils import getaddresses, parseaddr, parsedate_to_datetime

from app import credentials
from app.db import get_session
from app.imap_sync import _quote, _search_uids, _select_readonly, imap_date
from app.mail import inbound, transport
from app.mailbox_service import as_form_values, get_primary, server_config

CACHE_TTL_S = 60
MAX_LIST = 200
_cache: dict[tuple, tuple[float, dict]] = {}
_lock = threading.Lock()


class MailboxUnavailable(Exception):
    """Boîte non configurée, mot de passe absent ou serveur injoignable : message lisible."""


log = logging.getLogger(__name__)


@dataclass
class _Ctx:
    cfg: transport.ServerConfig
    sent_folder: str | None
    watched: list[str]


def _context() -> _Ctx:
    with get_session() as s:
        mb = get_primary(s)
        if mb is None:
            raise MailboxUnavailable("Aucune boîte mail configurée : renseignez-la dans Réglages.")
        password = credentials.get_password(mb.email)
        if not password:
            raise MailboxUnavailable("Mot de passe de la boîte introuvable : ressaisissez-le dans Réglages.")
        return _Ctx(server_config(as_form_values(mb), password), mb.sent_folder, list(mb.watched_folders or []))


def _open(ctx: _Ctx, imap_factory=None):
    try:
        return (imap_factory or transport.open_imap)(ctx.cfg)
    except Exception as exc:  # noqa: BLE001
        raise MailboxUnavailable(transport.explain_error(exc, "IMAP", ctx.cfg.imap_host, ctx.cfg.imap_port)) from None


def _close(conn) -> None:
    try:
        conn.logout()
    except Exception:  # noqa: BLE001
        pass


def _decode(value) -> str:
    if value is None:
        return ""
    try:
        return str(make_header(decode_header(str(value)))).strip()
    except Exception:  # noqa: BLE001
        return str(value).strip()


def _date(value) -> datetime | None:
    try:
        d = parsedate_to_datetime(str(value))
        return (d if d.tzinfo else d.replace(tzinfo=timezone.utc)).astimezone(timezone.utc)
    except (TypeError, ValueError, IndexError):
        return None


def _heal_sent_folder(ctx: _Ctx, items) -> _Ctx:
    """V3.8 : dossier des envoyés réglé sur la boîte de réception (chaque email envoyé y
    revenait « de vous-même ») : on le remplace par le vrai dossier Envoyés du serveur s'il existe."""
    found = transport.detect_special(items, "\\Sent", transport._SENT_GUESSES)
    if not found or found.upper() == "INBOX":
        return ctx
    with get_session() as s:
        mb = get_primary(s)
        if mb is not None and (mb.sent_folder or "").strip().upper() == "INBOX":
            log.warning("Dossier des envoyés corrigé : %r -> %r", mb.sent_folder, found)
            mb.sent_folder = found
            s.commit()
    return _Ctx(ctx.cfg, found, ctx.watched)


def folders(imap_factory=None) -> dict:
    ctx = _context()
    conn = _open(ctx, imap_factory)
    try:
        items = transport.list_folders(conn)
    finally:
        _close(conn)
    if (ctx.sent_folder or "").strip().upper() == "INBOX":  # (vide = choix volontaire, ex. Gmail : on n'y touche pas)
        ctx = _heal_sent_folder(ctx, items)
    out = [{"raw": f.raw_name, "display": f.display_name, **folder_label(f.raw_name, f.display_name, ctx.sent_folder)}
           for f in items]
    return {"items": sorted(out, key=lambda f: (f["rank"], f["label"].lower())), "sent": ctx.sent_folder, "watched": ctx.watched}


# V2.7 : noms « métier » au lieu de INBOX.Sent, INBOX.Junk… (le nom exact reste utilisé pour le serveur)
_LABELS = [
    (("inbox",), "Boîte de réception", 0),
    (("sent", "sent items", "sent messages", "envoyes", "elements envoyes"), "Envoyés", 1),
    (("archive", "archives"), "Archives", 2),
    (("drafts", "brouillons"), "Brouillons", 3),
    (("junk", "courrier indesirable", "indesirables"), "Indésirables", 4),
    (("spam",), "Spam", 5),
    (("trash", "deleted items", "deleted messages", "corbeille", "elements supprimes"), "Corbeille", 6),
]


def folder_label(raw: str, display: str, sent_folder: str | None = None) -> dict:
    if sent_folder and raw == sent_folder:
        return {"label": "Envoyés", "rank": 1}
    name = display or raw
    for prefix in ("INBOX.", "INBOX/", "Inbox.", "Inbox/"):
        if name.startswith(prefix) and len(name) > len(prefix):
            name = name[len(prefix):]
            break
    key = inbound.fold(name).strip()
    for keys, label, rank in _LABELS:
        if key in keys:
            return {"label": label, "rank": rank}
    return {"label": name.replace(".", " › ").replace("/", " › "), "rank": 10}


_HEADER_FIELDS = ("FROM TO CC SUBJECT DATE MESSAGE-ID IN-REPLY-TO REFERENCES CONTENT-TYPE "
                  "LIST-UNSUBSCRIBE LIST-ID PRECEDENCE AUTO-SUBMITTED")


def search_criteria(q: str = "", person: str = "") -> list[str]:
    """V3.4.4 : recherche faite PAR LE SERVEUR MAIL (rien n'est copié chez nous).
    `q` : chaque mot doit se trouver dans l'expéditeur, un destinataire ou l'objet. Les mots avec
    accents sont laissés au filtre de l'écran (le protocole IMAP ne les accepte pas tels quels).
    `person` : emails reçus de cette adresse ou envoyés à elle (À ou Cc)."""
    out: list[str] = []
    for w in q.split()[:5]:
        if len(w) >= 2 and w.isascii():
            v = _quote(w)
            out += ["OR", "FROM", v, "OR", "TO", v, "SUBJECT", v]
    if person and person.isascii():
        v = _quote(person)
        out += ["OR", "FROM", v, "OR", "TO", v, "CC", v]
    return out


def list_messages(folder: str = "INBOX", days: int = 30, refresh: bool = False, now: datetime | None = None,
                  imap_factory=None, criteria: list[str] | None = None) -> dict:
    """Les emails des `days` derniers jours du dossier, les plus récents d'abord (200 au plus).
    `criteria` (voir search_criteria) : seulement ceux qui correspondent, cherchés par le serveur mail."""
    criteria = list(criteria or [])
    key = (_who(), folder, days, tuple(criteria))  # V3 : un cache par employé (sinon B verrait la liste de A)
    with _lock:
        hit = _cache.get(key)
        if hit and not refresh and time.monotonic() - hit[0] < CACHE_TTL_S:
            return hit[1]
    now = now or datetime.now(timezone.utc)
    ctx = _context()
    conn = _open(ctx, imap_factory)
    try:
        try:
            _select_readonly(conn, folder)
            uids = _search_uids(conn, ["SINCE", imap_date((now - timedelta(days=days)).date()), *criteria])
        except imaplib.IMAP4.error as exc:
            raise MailboxUnavailable(f"Dossier « {folder} » illisible : {exc}") from None
        found = len(uids)
        uids = uids[-MAX_LIST:]
        items = []
        for i in range(0, len(uids), 50):
            chunk = ",".join(str(u) for u in uids[i:i + 50])
            typ, data = conn.uid("FETCH", chunk, f"(FLAGS RFC822.SIZE BODY.PEEK[HEADER.FIELDS ({_HEADER_FIELDS})])")
            if typ != "OK":
                raise MailboxUnavailable(f"Lecture du dossier « {folder} » refusée par le serveur.")
            for part in data:
                if not isinstance(part, tuple):
                    continue
                meta = part[0].decode("latin-1", "replace")
                uid = re.search(r"UID (\d+)", meta)
                if not uid:
                    continue
                h = message_from_bytes(part[1], policy=policy.compat32)
                name, addr = parseaddr(_decode(h.get("From")))
                ctype = str(h.get("Content-Type") or "").lower()
                when = _date(h.get("Date"))
                items.append({
                    "uid": int(uid.group(1)),
                    "from_name": name or addr, "from_email": addr.lower(),
                    "to": [a.lower() for _, a in getaddresses([_decode(h.get("To")), _decode(h.get("Cc"))]) if a],
                    "subject": _decode(h.get("Subject")),
                    "date": when.isoformat() if when else None,
                    "seen": "\\Seen" in meta,
                    "message_id": (inbound._ids(str(h.get("Message-ID") or "")) or [None])[0],
                    "has_attachments": "multipart/mixed" in ctype,
                    "size": int(m.group(1)) if (m := re.search(r"RFC822\.SIZE (\d+)", meta)) else None,
                    # V2.12 : pour « À répondre » (fil de la conversation, envois automatiques)
                    "refs": inbound._ids(" ".join(str(h.get(k) or "") for k in ("In-Reply-To", "References"))),
                    "bulk": bool(h.get("List-Unsubscribe") or h.get("List-Id")
                                 or str(h.get("Precedence") or "").lower() in ("bulk", "list", "junk")
                                 or str(h.get("Auto-Submitted") or "no").lower() != "no"),
                })
    finally:
        _close(conn)
    items.sort(key=lambda x: x["date"] or "", reverse=True)
    try:  # V3.7 : les expéditeurs (vrais, pas les envois automatiques) alimentent le carnet d'adresses
        from app import address_book
        address_book.record_seen([(i["from_name"], i["from_email"]) for i in items if not i["bulk"]],
                                 own={ctx.cfg.username} if getattr(ctx.cfg, "username", None) else None)
    except Exception:  # noqa: BLE001 – le carnet ne doit jamais empêcher d'afficher la boîte
        import logging
        logging.getLogger(__name__).warning("Carnet d'adresses non mis à jour", exc_info=True)
    result = {"folder": folder, "days": days, "searched": bool(criteria), "items": items, "found": found, "truncated": found > len(items),
              "fetched_at": now.isoformat()}
    with _lock:
        _cache[key] = (time.monotonic(), result)
    return result


# V2.19 : l'email brut est gardé EN MÉMOIRE 2 minutes (jamais sur le disque), le temps d'afficher
# ses images et d'ouvrir ses pièces jointes sans le retélécharger à chaque fois.
RAW_TTL_S = 120
RAW_MAX = 8
_raw_cache: dict[tuple, tuple[float, bytes]] = {}


def _who():
    """V3 : les numéros d'email (UID) sont propres à chaque boîte : le cache doit être
    séparé par employé, sinon l'email n°42 de A s'afficherait pour l'email n°42 de B."""
    from app.current import user_id
    return user_id()


def _fetch_raw(folder: str, uid: int, imap_factory=None) -> bytes:
    key = (_who(), folder, int(uid))
    with _lock:
        hit = _raw_cache.get(key)
        if hit and time.monotonic() - hit[0] < RAW_TTL_S:
            return hit[1]
    ctx = _context()
    conn = _open(ctx, imap_factory)
    try:
        try:
            _select_readonly(conn, folder)
            typ, data = conn.uid("FETCH", str(int(uid)), "(BODY.PEEK[])")  # PEEK : reste « non lu »
        except imaplib.IMAP4.error as exc:
            raise MailboxUnavailable(f"Email illisible : {exc}") from None
    finally:
        _close(conn)
    raw = next((p[1] for p in data or [] if isinstance(p, tuple)), None) if typ == "OK" else None
    if raw is None:
        raise MailboxUnavailable("Cet email n'existe plus dans ce dossier (déplacé ou supprimé ?).")
    with _lock:
        _raw_cache[key] = (time.monotonic(), raw)
        for k in sorted(_raw_cache, key=lambda k: _raw_cache[k][0])[:-RAW_MAX]:
            del _raw_cache[k]
    return raw


def _leaves(msg) -> list:
    return [p for p in msg.walk() if not p.is_multipart()]


def _cid(part) -> str:
    return (str(part.get("Content-ID") or "")).strip().strip("<>")


def _part_name(part, i: int) -> str:
    name = part.get_filename()
    if name:
        return _decode(name)
    ext = {"image/png": ".png", "image/jpeg": ".jpg", "image/gif": ".gif", "application/pdf": ".pdf"}.get(part.get_content_type(), "")
    return f"{'image' if part.get_content_maintype() == 'image' else 'piece-jointe'}-{i}{ext}"


_DANGEROUS = [
    (re.compile(r"(?is)<script\b.*?</script\s*>"), ""),
    (re.compile(r"(?is)<(iframe|object|embed|applet|form|base|link)\b[^>]*>"), ""),
    (re.compile(r"(?is)</(iframe|object|embed|applet|form)\s*>"), ""),
    (re.compile(r"(?is)<meta\b[^>]*http-equiv[^>]*>"), ""),
]
_REMOTE = re.compile(r"""(?i)(<img\b[^>]*\ssrc\s*=\s*["']?\s*https?:|background\s*=\s*["']?\s*https?:|url\(\s*["']?\s*https?:)""")


def clean_html(html_text: str) -> str:
    """Le HTML est de toute façon affiché dans un cadre isolé (sans scripts ni formulaires) ;
    on retire en plus ce qui n'a rien à faire dans un email."""
    for rx, repl in _DANGEROUS:
        html_text = rx.sub(repl, html_text)
    return html_text


def get_message(folder: str, uid: int, imap_factory=None) -> dict:
    from urllib.parse import quote
    raw = _fetch_raw(folder, uid, imap_factory)
    msg = message_from_bytes(raw, policy=policy.default)
    a = inbound.analyse(raw)
    name, addr = parseaddr(str(msg.get("From") or ""))
    body_parts = {id(p) for p in (msg.get_body(preferencelist=("plain",)), msg.get_body(preferencelist=("html",))) if p is not None}
    html_part = msg.get_body(preferencelist=("html",))
    html_text, remote = None, False
    leaves = _leaves(msg)
    part_url = lambda i: f"/api/mailbox/messages/{int(uid)}/part/{i}?folder={quote(folder, safe='')}"  # noqa: E731
    if html_part is not None:
        try:
            html_text = html_part.get_content()
        except (LookupError, UnicodeDecodeError):
            html_text = (html_part.get_payload(decode=True) or b"").decode("utf-8", "replace")
        html_text = clean_html(html_text)
        for i, p in enumerate(leaves):  # images intégrées : cid:… -> adresse locale de la partie
            cid = _cid(p)
            if cid:
                html_text = re.sub(r"(?i)cid:" + re.escape(cid), part_url(i), html_text)
        remote = bool(_REMOTE.search(html_text))
    attachments = []
    for i, part in enumerate(leaves):
        if id(part) in body_parts:
            continue
        ctype = part.get_content_type()
        cid = _cid(part)
        inline = bool(cid and html_text and part_url(i) in html_text)
        if ctype.startswith("text/") and not part.get_filename():
            continue  # autre version du texte, pas une pièce jointe
        payload = part.get_payload(decode=True) or b""
        attachments.append({"index": i, "name": _part_name(part, i), "size": len(payload), "type": ctype,
                            "inline": inline, "viewable": ctype in VIEWABLE, "url": part_url(i),
                            "previewable": _previewable(ctype, _part_name(part, i))})
    return {
        "uid": int(uid), "folder": folder,
        "from_name": _decode(name) or addr, "from_email": addr.lower(),
        "to": inbound.addresses(str(msg.get("To") or "")), "cc": inbound.addresses(str(msg.get("Cc") or "")),
        "subject": a.subject, "date": a.received_at.isoformat(),
        "message_id": a.message_id, "references": a.referenced_ids,
        "kind": a.kind,  # reply / auto_reply / bounce_* / unsubscribe : simple indication
        "text": a.text, "full": a.full_text, "attachments": [x for x in attachments if not x["inline"]],
        "html": html_text, "remote_images": remote,
    }


# Types affichés directement dans le navigateur ; tout le reste est téléchargé (et s'ouvre avec
# Word, Excel… sur le PC). Jamais de HTML ni de SVG affiché tel quel : ils pourraient contenir du code.
VIEWABLE = {"image/png", "image/jpeg", "image/gif", "image/webp", "image/bmp", "application/pdf", "text/plain"}


def _previewable(ctype: str, name: str) -> bool:
    from app.attachment_preview import kind_of
    return kind_of(ctype, name) is not None


def forwardable_parts(folder: str, uid: int, imap_factory=None) -> list[tuple[bytes, str, str]]:
    """V2.19 : pièces jointes ET images intégrées d'un email, pour le transférer (le transfert part
    en texte : une photo dans le corps devient une pièce jointe, elle n'est pas perdue)."""
    msg = message_from_bytes(_fetch_raw(folder, uid, imap_factory), policy=policy.default)
    body_parts = {id(p) for p in (msg.get_body(preferencelist=("plain",)), msg.get_body(preferencelist=("html",))) if p is not None}
    out = []
    for i, part in enumerate(_leaves(msg)):
        if id(part) in body_parts or (part.get_content_type().startswith("text/") and not part.get_filename()):
            continue
        out.append((part.get_payload(decode=True) or b"", part.get_content_type(), _part_name(part, i)))
    return out


def get_part(folder: str, uid: int, index: int, imap_factory=None) -> tuple[bytes, str, str]:
    """(contenu, type, nom de fichier) d'une partie de l'email (pièce jointe ou image)."""
    msg = message_from_bytes(_fetch_raw(folder, uid, imap_factory), policy=policy.default)
    leaves = _leaves(msg)
    if not 0 <= index < len(leaves):
        raise MailboxUnavailable("Pièce jointe introuvable.")
    part = leaves[index]
    return part.get_payload(decode=True) or b"", part.get_content_type(), _part_name(part, index)


def invalidate(folder: str | None = None) -> None:
    me = _who()
    with _lock:
        for k in [k for k in _cache if k[0] == me and (folder is None or k[1] == folder)]:
            del _cache[k]
        for k in [k for k in _raw_cache if k[0] == me and (folder is None or k[1] == folder)]:
            del _raw_cache[k]
        if folder in (None, "INBOX"):
            _unread.pop(me, None)


def _quote_folder(name: str) -> str:  # réexport pour l'envoi manuel
    return _quote(name)


# ------------------------------------------------------------------ V2.20 : archiver
# Seule écriture de la boîte mail faite par l'application, et à la demande d'Omar :
# l'email est DÉPLACÉ (jamais supprimé) dans le dossier d'archives, comme « Archiver » dans
# Outlook. Rien d'autre ne change (ni lu / non lu, ni les autres emails du dossier).

ARCHIVE_NAMES = ("archive", "archives")
JUNK_NAMES = ("junk", "spam", "courrier indesirable", "indesirables", "bulk", "junk e-mail", "junk email")


def _caps(conn) -> set[str]:
    try:
        typ, data = conn.capability()
        if typ == "OK" and data:
            return {c.upper() for c in b" ".join(data).decode("ascii", "replace").split()}
    except Exception:  # noqa: BLE001
        pass
    return {str(c).upper() for c in getattr(conn, "capabilities", ())}


def archive_folder(conn) -> str:
    """Dossier d'archives du serveur : celui marqué \\Archive, sinon « Archive(s) », sinon on le crée
    (« INBOX.Archive » sur les serveurs cPanel, « Archive » ailleurs)."""
    items = transport.list_folders(conn)
    for f in items:
        if any(fl.lower() == "\\archive" for fl in f.flags):
            return f.raw_name
    for f in items:
        name = f.raw_name
        for prefix in ("INBOX.", "INBOX/"):
            if name.startswith(prefix):
                name = name[len(prefix):]
        if inbound.fold(name) in ARCHIVE_NAMES:
            return f.raw_name
    target = "INBOX.Archive" if any(f.raw_name.startswith("INBOX.") for f in items) else "Archive"
    typ, data = conn.create(_quote(target))
    if typ != "OK":
        raise MailboxUnavailable(f"Impossible de créer le dossier d'archives : {data!r}")
    try:
        conn.subscribe(_quote(target))
    except Exception:  # noqa: BLE001 – l'abonnement sert seulement à le montrer dans les autres messageries
        pass
    return target


def junk_folder(conn) -> str:
    """V3 : dossier des indésirables du serveur : celui marqué \\Junk, sinon « Junk / Spam /
    Courrier indésirable », sinon on le crée (« INBOX.Junk » sur cPanel, « Junk » ailleurs)."""
    items = transport.list_folders(conn)
    for f in items:
        if any(fl.lower() in ("\\junk", "\\spam") for fl in f.flags):
            return f.raw_name
    for f in items:
        name = f.raw_name
        for prefix in ("INBOX.", "INBOX/"):
            if name.startswith(prefix):
                name = name[len(prefix):]
        if inbound.fold(name) in JUNK_NAMES:
            return f.raw_name
    target = "INBOX.Junk" if any(f.raw_name.startswith("INBOX.") for f in items) else "Junk"
    typ, data = conn.create(_quote(target))
    if typ != "OK":
        raise MailboxUnavailable(f"Impossible de créer le dossier des indésirables : {data!r}")
    try:
        conn.subscribe(_quote(target))
    except Exception:  # noqa: BLE001
        pass
    return target


def _target(conn, kind: str) -> str:
    return junk_folder(conn) if kind == "junk" else archive_folder(conn)


def _move(conn, uid: int, dest: str) -> None:
    caps = _caps(conn)
    if "MOVE" in caps:
        typ, data = conn.uid("MOVE", str(int(uid)), _quote(dest))
        if typ != "OK":
            raise MailboxUnavailable(f"Déplacement refusé par le serveur : {data!r}")
        return
    if "UIDPLUS" not in caps:
        raise MailboxUnavailable("Ce serveur ne permet pas de déplacer un email sans risque.")
    typ, data = conn.uid("COPY", str(int(uid)), _quote(dest))
    if typ != "OK":
        raise MailboxUnavailable(f"Copie refusée par le serveur : {data!r}")
    conn.uid("STORE", str(int(uid)), "+FLAGS.SILENT", r"(\Deleted)")
    conn.uid("EXPUNGE", str(int(uid)))  # UID EXPUNGE : uniquement CET email


def archive(folder: str, uid: int, imap_factory=None, kind: str = "archive") -> dict:
    """Déplace l'email vers les archives (kind="archive") ou les indésirables (kind="junk")."""
    ctx = _context()
    conn = _open(ctx, imap_factory)
    try:
        dest = _target(conn, kind)
        if dest == folder:
            raise MailboxUnavailable("Cet email est déjà dans les indésirables." if kind == "junk"
                                     else "Cet email est déjà dans les archives.")
        typ, _ = conn.select(_quote(folder))  # lecture-écriture, pour ce seul déplacement
        if typ != "OK":
            raise MailboxUnavailable(f"Dossier « {folder} » inaccessible.")
        typ, data = conn.uid("FETCH", str(int(uid)), "(BODY.PEEK[HEADER.FIELDS (MESSAGE-ID)])")
        raw = next((p[1] for p in data or [] if isinstance(p, tuple)), b"") if typ == "OK" else b""
        mid = str(message_from_bytes(raw or b"", policy=policy.default).get("Message-ID") or "").strip()
        _move(conn, uid, dest)
    except imaplib.IMAP4.error as exc:
        raise MailboxUnavailable(f"Déplacement impossible : {exc}") from None
    finally:
        _close(conn)
    invalidate()
    return {"archive_folder": dest, "message_id": mid}


def unarchive(message_id: str, to_folder: str = "INBOX", imap_factory=None, kind: str = "archive") -> bool:
    """« Annuler » : remet l'email (retrouvé par son Message-ID) dans son dossier d'origine."""
    if not message_id:
        return False
    ctx = _context()
    conn = _open(ctx, imap_factory)
    try:
        dest = _target(conn, kind)
        typ, _ = conn.select(_quote(dest))
        if typ != "OK":
            return False
        uids = _search_uids(conn, ["HEADER", "Message-ID", _quote(message_id)])
        if not uids:
            return False
        _move(conn, uids[-1], to_folder)
    except imaplib.IMAP4.error as exc:
        raise MailboxUnavailable(f"Annulation impossible : {exc}") from None
    finally:
        _close(conn)
    invalidate()
    return True


# --------------------------------------------------------------------------- V3.7.1 : non lus
# Comme dans une messagerie : un chiffre à côté de « Boîte mail » (non lus de la boîte de réception),
# et l'email ouvert dans l'appli passe « lu » sur le serveur (donc aussi dans le webmail).
UNREAD_TTL_S = 45
_unread: dict = {}


def unread_count(refresh: bool = False, imap_factory=None) -> int:
    """Non lus de INBOX, via IMAP STATUS (léger : rien n'est téléchargé), gardé 45 s par employé."""
    key = _who()
    with _lock:
        hit = _unread.get(key)
        if hit and not refresh and time.monotonic() - hit[0] < UNREAD_TTL_S:
            return hit[1]
    ctx = _context()
    conn = _open(ctx, imap_factory)
    try:
        typ, data = conn.status("INBOX", "(UNSEEN)")
        m = re.search(rb"UNSEEN (\d+)", b" ".join(d if isinstance(d, bytes) else str(d).encode() for d in data or []))
        n = int(m.group(1)) if typ == "OK" and m else 0
    except imaplib.IMAP4.error as exc:
        raise MailboxUnavailable(f"Boîte de réception illisible : {exc}") from None
    finally:
        _close(conn)
    with _lock:
        _unread[key] = (time.monotonic(), n)
    return n


def set_seen(folder: str, uid: int, seen: bool = True, imap_factory=None) -> None:
    """Marque l'email lu (ou non lu) sur le serveur ; la liste et le compteur sont mis à jour."""
    ctx = _context()
    conn = _open(ctx, imap_factory)
    try:
        typ, _ = conn.select(_quote(folder))  # lecture-écriture, pour ce seul drapeau
        if typ != "OK":
            raise MailboxUnavailable(f"Dossier « {folder} » inaccessible.")
        conn.uid("STORE", str(int(uid)), "+FLAGS.SILENT" if seen else "-FLAGS.SILENT", r"(\Seen)")
    except imaplib.IMAP4.error as exc:
        raise MailboxUnavailable(f"Email non mis à jour : {exc}") from None
    finally:
        _close(conn)
    me = _who()
    with _lock:
        _unread.pop(me, None)
        for k, (_t, res) in _cache.items():  # la liste en mémoire suit, sans relire le serveur
            if k[0] == me and k[1] == folder:
                for it in res["items"]:
                    if it["uid"] == int(uid):
                        it["seen"] = seen

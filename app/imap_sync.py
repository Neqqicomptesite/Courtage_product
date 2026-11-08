"""Synchronisation IMAP : lit les nouveaux messages et en tire les conséquences (§6.7).

Règles de prudence :
- lecture SEULE : dossiers ouverts en lecture (EXAMINE), contenu lu avec
  BODY.PEEK[] (le message reste « non lu » dans Outlook), rien n'est déplacé
  ni supprimé ;
- on ne relit jamais deux fois le même message (UIDVALIDITY + dernier UID lu,
  et contrôle par Message-ID en plus) ;
- au tout premier passage sur un dossier, on ne lit que les messages reçus
  depuis le premier envoi de l'app (sinon on analyserait des années de boîte) ;
- en mode test, une réponse arrête la séquence concernée mais ne modifie ni le
  statut du contact ni la liste d'exclusion (le message venait d'Omar lui-même).
"""
from __future__ import annotations

import imaplib
import logging
import re
import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import credentials, settings_store, suppression
from app.db import get_session
from app.mail import inbound, transport
from app.mailbox_service import as_form_values, get_primary, server_config
from app import sequences_service as ss
from app.models import Campaign, Contact, Enrollment, EventLog, ImapState, Mailbox, Message, Sequence
from app.timeutil import to_local, utcnow

log = logging.getLogger(__name__)
STALE_AFTER = timedelta(minutes=5)  # V2.17 : boîte relue toutes les 5 minutes (10 avant)
FETCH_BATCH = 50
OPEN = ("scheduled", "sending", "waiting", "error", "needs_review")
_sync_locks: dict = {}          # V3 : un verrou par employé (la synchro de A ne bloque pas celle de B)
_locks_guard = threading.Lock()


def _sync_lock() -> threading.Lock:
    from app.current import user_id
    with _locks_guard:
        return _sync_locks.setdefault(user_id(), threading.Lock())


@dataclass
class SyncReport:
    ok: bool = True
    error: str = ""
    counts: dict = field(default_factory=dict)

    def add(self, kind: str) -> None:
        self.counts[kind] = self.counts.get(kind, 0) + 1


# ------------------------------------------------------------------ IMAP bas niveau

def _quote(name: str) -> str:
    return '"' + name.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _select_readonly(conn: imaplib.IMAP4, folder: str) -> int:
    typ, _ = conn.select(_quote(folder), readonly=True)  # EXAMINE : aucune modification possible
    if typ != "OK":
        raise imaplib.IMAP4.error(f"Dossier « {folder} » inaccessible")
    _, data = conn.response("UIDVALIDITY")
    return int(data[0]) if data and data[0] else 0


_MONTHS_EN = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def imap_date(d) -> str:
    """« 03-Nov-2026 » : IMAP exige les mois en anglais. strftime("%b") suivrait la langue du
    système et donnerait « nov. » sur un Windows français, que le serveur refuserait."""
    return f"{d.day:02d}-{_MONTHS_EN[d.month - 1]}-{d.year}"


def _search_uids(conn: imaplib.IMAP4, criteria: list[str]) -> list[int]:
    typ, data = conn.uid("SEARCH", None, *criteria)
    if typ != "OK":
        raise imaplib.IMAP4.error(f"SEARCH refusé : {data!r}")
    return sorted(int(x) for x in (data[0] or b"").split())


def _fetch(conn: imaplib.IMAP4, uids: list[int]):
    for i in range(0, len(uids), FETCH_BATCH):
        chunk = ",".join(str(u) for u in uids[i:i + FETCH_BATCH])
        typ, data = conn.uid("FETCH", chunk, "(BODY.PEEK[])")  # PEEK : ne marque pas comme lu
        if typ != "OK":
            raise imaplib.IMAP4.error(f"FETCH refusé : {data!r}")
        for item in data:
            if isinstance(item, tuple):
                m = re.search(rb"UID (\d+)", item[0])
                if m:
                    yield int(m.group(1)), item[1]


# ---------------------------------------------------------------------- correspondance

@dataclass
class Match:
    contact: Contact | None = None
    enrollment: Enrollment | None = None
    sent: Message | None = None          # email de l'app auquel ce message répond
    suggestion: Contact | None = None    # même domaine qu'un contact (réponse non rattachée)
    how: str = ""


def _match(s: Session, a: inbound.Analysis) -> Match:
    # 1) l'email cite un de nos Message-ID : correspondance certaine
    if a.referenced_ids:
        sent = s.scalars(select(Message).where(Message.direction == "out", Message.message_id.in_(a.referenced_ids))
                         .order_by(Message.id.desc())).first()
        # Un email écrit à la main depuis la boîte (V2.4, sans inscription) : la conversation vit
        # dans la boîte mail, pas dans les réponses de campagne. On continue : si l'expéditeur est
        # un prospect inscrit, l'étape 2 arrêtera quand même sa séquence.
        if sent and sent.enrollment_id is not None:
            return Match(s.get(Contact, sent.contact_id) if sent.contact_id else None,
                         s.get(Enrollment, sent.enrollment_id), sent, how="message_id")
    # Rebond structuré : le destinataire final désigne le contact
    if a.bounce and a.bounce.recipient:
        c = s.scalars(select(Contact).where(Contact.email == a.bounce.recipient)).first()
        if c:
            return Match(c, _latest_enrollment(s, c), how="final_recipient")
    # 2) l'expéditeur est un contact connu
    c = s.scalars(select(Contact).where(Contact.email == a.sender)).first()
    if c and _latest_enrollment(s, c):
        return Match(c, _latest_enrollment(s, c), how="from")
    # 3) même domaine qu'un contact inscrit (hors messageries gratuites) : à rattacher à la main
    domain = a.sender.rsplit("@", 1)[-1]
    if domain and not inbound.is_free_mail(domain):
        c = s.scalars(select(Contact).join(Enrollment, Enrollment.contact_id == Contact.id)
                      .where(Contact.email.like(f"%@{domain}")).order_by(Enrollment.created_at.desc())).first()
        if c:
            return Match(suggestion=c, how="domain")
    return Match()


def _latest_enrollment(s: Session, c: Contact) -> Enrollment | None:
    return s.scalars(select(Enrollment).where(Enrollment.contact_id == c.id)
                     .order_by(Enrollment.created_at.desc())).first()


# ------------------------------------------------------------------------ effets

def _event(s: Session, text: str, level="info", entity="contact", entity_id=None) -> None:
    s.add(EventLog(level=level, entity=entity, entity_id=entity_id, text=text))


def stop_open_enrollments(s: Session, contact: Contact, status: str, reason: str) -> int:
    n = 0
    for e in s.scalars(select(Enrollment).where(Enrollment.contact_id == contact.id, Enrollment.status.in_(OPEN))):
        e.status, e.stop_reason, e.next_due_at = status, reason, None
        n += 1
    return n


def _stop_same_company(s: Session, contact: Contact, test_mode: bool) -> int:
    """Option « arrêter si quelqu'un d'autre de la même entreprise répond » (§6.5)."""
    domain = contact.email.rsplit("@", 1)[-1]
    if inbound.is_free_mail(domain):
        return 0
    n = 0
    campaigns = {c.id for c in s.scalars(select(Campaign).join(Enrollment, Enrollment.campaign_id == Campaign.id)
                                         .where(Enrollment.contact_id == contact.id, Campaign.stop_on_domain_reply))}
    if not campaigns:
        return 0
    for e, other in s.execute(select(Enrollment, Contact).join(Contact, Contact.id == Enrollment.contact_id)
                              .where(Enrollment.campaign_id.in_(campaigns), Enrollment.status.in_(OPEN),
                                     Contact.id != contact.id, Contact.email.like(f"%@{domain}"))):
        e.status, e.stop_reason, e.next_due_at = "stopped", "domain_reply", None
        _event(s, f"Relances arrêtées : un collègue ({contact.email}) a répondu", entity_id=other.id)
        n += 1
    return n


def _only_this_dossier(s: Session, msg: Message, precise: bool) -> Enrollment | None:
    """V2.23 : une personne peut avoir plusieurs dossiers de gestion/souscription en cours (un G1
    par avenant). Quand sa réponse cite à coup sûr l'email d'un de ces dossiers (Message-ID), on
    n'arrête que ce dossier. Sinon (email écrit à part, prospection), on arrête tout, par prudence."""
    if not precise or msg.enrollment_id is None:
        return None
    enr = s.get(Enrollment, msg.enrollment_id)
    camp = s.get(Campaign, enr.campaign_id) if enr else None
    seq = s.get(Sequence, camp.sequence_id) if camp else None
    return enr if seq is not None and not ss.is_prospection(seq) else None


def apply_effects(s: Session, msg: Message, contact: Contact, test_mode: bool, auto_reply_continues: bool,
                  precise: bool = False) -> None:
    """Conséquences d'un message reçu rattaché à un contact."""
    tag = " (mode test : statut du contact inchangé)" if test_mode else ""
    if msg.kind == "reply":
        one = _only_this_dossier(s, msg, precise)
        if one is not None:
            n = 0
            if one.status in OPEN:
                one.status, one.stop_reason, one.next_due_at = "replied", "reply", None
                n = 1
            if not test_mode and contact.kind == "prospect":
                contact.global_status = "replied"
            _event(s, f"Réponse reçue : relances de ce dossier arrêtées, ses autres dossiers continuent{tag}",
                   entity_id=contact.id)
            return
        n = stop_open_enrollments(s, contact, "replied", "reply")
        if not test_mode:
            if contact.kind == "prospect":  # V2.23 : « A répondu » est un statut de prospection
                contact.global_status = "replied"
            _stop_same_company(s, contact, test_mode)
        _event(s, f"Réponse reçue : {n} séquence(s) arrêtée(s){tag}", entity_id=contact.id)
    elif msg.kind == "unsubscribe":
        n = stop_open_enrollments(s, contact, "unsubscribed", "unsubscribe")
        msg.classification = "unsubscribe"
        if not test_mode:
            contact.global_status = "unsubscribed"
            suppression.add(s, contact.email, f"STOP reçu le {to_local(msg.received_at):%d/%m/%Y}")
        _event(s, f"Demande de désinscription (STOP) : {n} séquence(s) arrêtée(s){tag}", "warning", entity_id=contact.id)
    elif msg.kind == "bounce_hard":
        if test_mode:
            _event(s, f"Rebond définitif ignoré{tag}", entity_id=contact.id)
            return
        n = stop_open_enrollments(s, contact, "bounced", "bounce_hard")
        contact.global_status = "bounced"
        _event(s, f"Rebond définitif : adresse invalide, {n} séquence(s) arrêtée(s)", "warning", entity_id=contact.id)
    elif msg.kind == "bounce_soft":
        _event(s, "Rebond temporaire (boîte pleine, serveur indisponible…) : la séquence continue", entity_id=contact.id)
    elif msg.kind == "auto_reply":
        msg.classification = "out_of_office"
        if auto_reply_continues:
            _event(s, "Message d'absence reçu : la séquence continue"
                      + (f" (retour : {msg.return_date})" if msg.return_date else ""), entity_id=contact.id)
        else:
            n = stop_open_enrollments(s, contact, "stopped", "out_of_office")
            _event(s, f"Message d'absence reçu : {n} séquence(s) arrêtée(s)", entity_id=contact.id)


# ---------------------------------------------------------------------- traitement

def process_raw(s: Session, mb: Mailbox, raw: bytes, folder: str | None, uid: int | None,
                report: SyncReport) -> Message | None:
    a = inbound.analyse(raw)
    own_ids = a.message_id and s.scalar(select(func.count(Message.id)).where(
        Message.direction == "out", Message.message_id == a.message_id))
    if own_ids:
        report.add("ignored_own")  # nos propres emails (mode test : ils arrivent dans la boîte d'Omar)
        return None
    if a.message_id and s.scalar(select(func.count(Message.id)).where(
            Message.direction == "in", Message.message_id == a.message_id)):
        report.add("already_seen")
        return None

    # Cotalis : réponse d'une compagnie à une demande de cotation (fil d'un dossier)
    from app import quotes
    if quotes.on_inbound(s, mb.id, a, raw, folder, uid):
        report.add("quote_reply")
        return None

    m = _match(s, a)
    if m.contact is None and m.suggestion is None:
        report.add("unrelated")  # sans rapport avec la prospection : on ne stocke rien
        return None

    test_mode = m.sent.test_mode if m.sent is not None else bool(settings_store.get(s, "test_mode"))
    kind = a.kind if m.contact is not None else "unmatched"
    msg = Message(enrollment_id=m.enrollment.id if m.enrollment else None,
                  contact_id=m.contact.id if m.contact else None, direction="in", kind=kind,
                  message_id=a.message_id, in_reply_to=a.in_reply_to, references_header=" ".join(a.references) or None,
                  subject=a.subject[:998], body_text=a.text[:20000], body_full=a.full_text[:50000],
                  received_at=a.received_at, imap_folder=folder, imap_uid=uid, raw_headers=a.raw_headers,
                  return_date=a.return_date, test_mode=test_mode,
                  suggested_contact_id=m.suggestion.id if m.suggestion else None,
                  to_email=mb.email, mailbox_id=mb.id)
    s.add(msg)
    s.flush()
    if m.contact is not None:
        apply_effects(s, msg, m.contact, test_mode, bool(settings_store.get(s, "auto_reply_continues")),
                      precise=m.how == "message_id")
    else:
        _event(s, f"Réponse non rattachée de {a.sender} : réponse probable de {m.suggestion.company or m.suggestion.email}",
               entity_id=m.suggestion.id)
    report.add(kind)
    return msg


def _first_sync_since(s: Session, now: datetime) -> datetime:
    first_out = s.scalar(select(func.min(Message.sent_at)).where(Message.direction == "out"))
    return min(first_out, now) if first_out else now - timedelta(days=1)


def sync(now: datetime | None = None, imap_factory=None) -> SyncReport:
    now = now or utcnow()
    imap_factory = imap_factory or transport.open_imap
    report = SyncReport()
    lock = _sync_lock()
    if not lock.acquire(blocking=False):
        return SyncReport(ok=True, error="Synchronisation déjà en cours")
    try:
        with get_session() as s:
            settings_store.set_(s, "last_imap_attempt", now.isoformat())
            s.commit()
            mb = get_primary(s)
            if mb is None or not mb.imap_host:
                return SyncReport(ok=False, error="Boîte mail non configurée")
            password = credentials.get_password(mb.email)
            if not password:
                return _fail(s, "Mot de passe de la boîte introuvable")
            cfg = server_config(as_form_values(mb), password)
            try:
                conn = imap_factory(cfg)
            except Exception as exc:  # noqa: BLE001
                return _fail(s, transport.explain_error(exc, "IMAP", cfg.imap_host, cfg.imap_port))
            try:
                folders = list(mb.watched_folders or ["INBOX"])
                for folder in folders:
                    _sync_folder(s, conn, mb, folder, now, report)
                # V2.21 : une réponse rangée (Archive) ou supprimée (Corbeille) depuis le téléphone,
                # Outlook ou le webmail AVANT que l'application l'ait lue arrête quand même les
                # relances. Ces dossiers en plus ne bloquent jamais la synchronisation.
                for folder in safety_folders(conn, folders):
                    try:
                        _sync_folder(s, conn, mb, folder, now, report)
                    except Exception:  # noqa: BLE001
                        s.rollback()
                        log.warning("Dossier %s illisible : ignoré pour cette fois", folder)
            except Exception as exc:  # noqa: BLE001
                s.rollback()
                return _fail(s, f"{type(exc).__name__} : {exc}")
            finally:
                try:
                    conn.logout()
                except Exception:  # noqa: BLE001
                    pass
            settings_store.set_(s, "last_imap_sync", now.isoformat())
            settings_store.set_(s, "imap_last_error", "")
            interesting = {k: v for k, v in report.counts.items() if k not in ("ignored_own", "already_seen", "unrelated")}
            if interesting:
                _event(s, "Synchronisation : " + ", ".join(f"{v} {k}" for k, v in interesting.items()), entity="imap")
            s.commit()
            if mb.sent_folder:  # V2.20 : copies dans « Envoyés » restées en attente
                from app import sent_copy
                try:
                    sent_copy.flush(cfg, mb.sent_folder, imap_factory)
                except Exception:  # noqa: BLE001
                    log.exception("Copies en attente dans « Envoyés » : nouvel essai plus tard")
            return report
    finally:
        lock.release()


SAFETY_FLAGS = ("\\archive", "\\trash")
SAFETY_NAMES = ("archive", "archives", "trash", "corbeille", "deleted items", "deleted messages", "elements supprimes")


def safety_folders(conn, already: list[str]) -> list[str]:
    """Dossiers Archive et Corbeille du serveur (repérés par leur marque, sinon par leur nom)."""
    try:
        items = transport.list_folders(conn)
    except Exception:  # noqa: BLE001
        return []
    out = []
    for f in items:
        name = f.raw_name
        short = re.split(r"[./]", f.display_name or name)[-1]
        if any(fl.lower() in SAFETY_FLAGS for fl in f.flags) or inbound.fold(short) in SAFETY_NAMES:
            if name not in already and name not in out:
                out.append(name)
    return out


def _fail(s: Session, text: str) -> SyncReport:
    settings_store.set_(s, "imap_last_error", text)
    _event(s, f"Synchronisation impossible : {text}", "warning", entity="imap")
    s.commit()
    log.warning("Synchronisation IMAP impossible : %s", text)
    return SyncReport(ok=False, error=text)


def _sync_folder(s: Session, conn, mb: Mailbox, folder: str, now: datetime, report: SyncReport) -> None:
    uidvalidity = _select_readonly(conn, folder)
    state = s.get(ImapState, (mb.id, folder))
    if state is None or state.uidvalidity != uidvalidity:
        # Premier passage, ou le serveur a renuméroté le dossier : on repart d'une date,
        # le contrôle par Message-ID évite de traiter deux fois le même message.
        uids = _search_uids(conn, ["SINCE", imap_date(to_local(_first_sync_since(s, now)))])
        if state is None:
            state = ImapState(mailbox_id=mb.id, folder=folder, uidvalidity=uidvalidity, last_uid=0)
            s.add(state)
        state.uidvalidity, state.last_uid = uidvalidity, 0
    else:
        uids = [u for u in _search_uids(conn, ["UID", f"{state.last_uid + 1}:*"]) if u > state.last_uid]
    for uid, raw in _fetch(conn, uids):
        try:
            process_raw(s, mb, raw, folder, uid, report)
        except Exception:  # noqa: BLE001 – un message illisible ne bloque pas les suivants
            log.exception("Message %s/%s illisible", folder, uid)
            report.add("error")
        state.last_uid = max(state.last_uid, uid)
    s.commit()


def sync_if_stale(now: datetime) -> bool:
    """Appelé par le moteur avant d'envoyer (§6.6 étape 2). Renvoie False si la boîte
    n'a pas pu être lue alors qu'elle aurait dû l'être : le moteur n'envoie pas."""
    with get_session() as s:
        last_ok = settings_store.get(s, "last_imap_sync")
        last_try = settings_store.get(s, "last_imap_attempt")
        mb = get_primary(s)
        if mb is None or not mb.imap_host:
            return True
    if last_ok and now - datetime.fromisoformat(last_ok) < STALE_AFTER:
        return True
    if last_try and now - datetime.fromisoformat(last_try) < STALE_AFTER and last_try != last_ok:
        return False  # échec récent : on ne réessaie pas chaque minute, et on n'envoie pas
    return sync(now).ok


# ------------------------------------------------------- rattachement manuel

def attach(message_id: int, contact_id: int) -> bool:
    """Réponse non rattachée -> l'utilisateur confirme le contact : on applique les effets."""
    with get_session() as s:
        msg, contact = s.get(Message, message_id), s.get(Contact, contact_id)
        if msg is None or contact is None or msg.kind != "unmatched":
            return False
        a = inbound.Analysis("reply", None, None, [], "", msg.subject, msg.received_at, msg.body_text, "")
        msg.contact_id = contact.id
        enr = _latest_enrollment(s, contact)
        msg.enrollment_id = enr.id if enr else None
        msg.kind = "unsubscribe" if inbound._is_unsubscribe(a.subject, a.text) else "reply"
        apply_effects(s, msg, contact, msg.test_mode, bool(settings_store.get(s, "auto_reply_continues")))
        s.commit()
        return True


def dismiss(message_id: int) -> bool:
    with get_session() as s:
        msg = s.get(Message, message_id)
        if msg is None or msg.kind != "unmatched":
            return False
        s.delete(msg)
        s.commit()
        return True

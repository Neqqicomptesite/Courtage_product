"""Moteur d'envoi (§6.6). C'est la partie la plus sensible de l'application.

Principes :
1. UN seul email par passage (une fois par minute) : jamais de rafale, même
   après une coupure du PC.
2. On enregistre l'email en base (statut « sending ») AVANT de parler au
   serveur SMTP. Si le PC s'éteint pendant l'envoi, on sait au redémarrage
   qu'un envoi était en cours : l'inscription passe « à vérifier » et n'est
   JAMAIS renvoyée automatiquement (pas de doublon chez le prospect).
3. Tout est revérifié juste avant l'envoi (statut du contact, liste
   d'exclusion, réponse reçue) : la situation a pu changer depuis l'inscription.
4. En mode test, le destinataire est remplacé par l'adresse d'Omar au moment
   de construire l'email : c'est le seul endroit où le destinataire est choisi.

Toutes les fonctions prennent `now` en paramètre : les tests peuvent ainsi
simuler des jours entiers d'envois en quelques secondes.
"""
from __future__ import annotations

import imaplib
import logging
import random
import smtplib
import ssl
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import sent_copy
from app import attachments_service, credentials, imap_sync, settings_store, suppression
from app import sequences_service as ss
from app.db import get_session
from app.mail import compose, transport
from app.mailbox_service import as_form_values, get_primary, server_config
from app.models import Campaign, Contact, Enrollment, EventLog, Mailbox, Message, Sequence
from app.scheduling import SendWindow
from app.timeutil import TZ, to_local, utcnow

log = logging.getLogger(__name__)

RETRY_DELAYS = [timedelta(minutes=5), timedelta(minutes=15), timedelta(minutes=60)]
STALE_SENDING = timedelta(minutes=10)
DUE_STATUSES = ("scheduled", "waiting")
OPEN_STATUSES = ("scheduled", "sending", "waiting", "error", "needs_review")
STOPPING_KINDS = ("reply", "unsubscribe", "bounce_hard")

# Un seul envoi à la fois, même si l'utilisateur clique « envoyer maintenant »
# pendant que la tâche planifiée tourne.
_send_lock = threading.Lock()


@dataclass
class TickResult:
    action: str          # closed | idle | cap_day | cap_hour | gap | sent | retry | failed | stopped | error
    detail: str = ""
    enrollment_id: int | None = None


# ----------------------------------------------------------------- utilitaires

def _event(s: Session, text: str, level: str = "info", entity: str = "enrollment",
           entity_id: int | None = None) -> None:
    s.add(EventLog(level=level, entity=entity, entity_id=entity_id, text=text))
    getattr(log, "warning" if level == "warning" else "error" if level == "error" else "info")(text)


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None


def _from_iso(v: str | None) -> datetime | None:
    return datetime.fromisoformat(v) if v else None


def _sent_query(mb: Mailbox):
    return (select(func.count(Message.id))
            .join(Enrollment, Enrollment.id == Message.enrollment_id)
            .join(Campaign, Campaign.id == Enrollment.campaign_id)
            .where(Message.direction == "out", Message.sent_at.is_not(None), Campaign.mailbox_id == mb.id))


def effective_daily_cap(s: Session, mb: Mailbox, now: datetime) -> int:
    """Plafond du jour, montée en charge comprise (§4)."""
    cap = mb.daily_cap
    if settings_store.get(s, "rampup_enabled"):
        first = s.scalar(select(func.min(Message.sent_at))
                         .join(Enrollment, Enrollment.id == Message.enrollment_id)
                         .join(Campaign, Campaign.id == Enrollment.campaign_id)
                         .where(Message.direction == "out", Campaign.mailbox_id == mb.id))
        days = settings_store.get(s, "rampup_days")
        if first is None or (to_local(now).date() - to_local(first).date()).days < days:
            cap = min(cap, settings_store.get(s, "rampup_per_day"))
    return cap


def counters(s: Session, mb: Mailbox, now: datetime) -> dict:
    local_midnight = datetime.combine(to_local(now).date(), datetime.min.time(), tzinfo=TZ)
    return {
        "today": s.scalar(_sent_query(mb).where(Message.sent_at >= local_midnight)) or 0,
        "last_hour": s.scalar(_sent_query(mb).where(Message.sent_at > now - timedelta(hours=1))) or 0,
        "daily_cap": effective_daily_cap(s, mb, now),
        "hourly_cap": mb.hourly_cap,
    }


def _back_status(enr: Enrollment) -> str:
    return "scheduled" if enr.current_step <= 1 else "waiting"


def stop_enrollment(s: Session, enr: Enrollment, status: str, reason: str) -> None:
    enr.status, enr.stop_reason, enr.next_due_at = status, reason, None


# ------------------------------------------------------------- protections

def mark_stale_sending(now: datetime) -> int:
    """Inscriptions restées « en cours d'envoi » plus de 10 min : le résultat est
    inconnu (coupure pendant l'envoi ?). On ne renvoie JAMAIS automatiquement."""
    with get_session() as s:
        stale = list(s.scalars(select(Enrollment).where(
            Enrollment.status == "sending", Enrollment.updated_at < now - STALE_SENDING)))
        for enr in stale:
            enr.status = "needs_review"
            enr.last_error = ("Envoi interrompu : vérifiez dans vos « Envoyés » si l'email est parti, "
                              "puis validez ou renvoyez.")
            _event(s, f"Inscription n°{enr.id} : envoi interrompu, à vérifier", "warning", entity_id=enr.id)
        s.commit()
        return len(stale)


def finish_campaigns(s: Session) -> None:
    # Une campagne « à l'unité » (V2.9) reste ouverte : d'autres envois viendront s'y ajouter.
    for camp in s.scalars(select(Campaign).where(Campaign.status == "active", Campaign.direct.is_(False))):
        still_open = s.scalar(select(func.count(Enrollment.id)).where(
            Enrollment.campaign_id == camp.id, Enrollment.status.in_(OPEN_STATUSES)))
        if not still_open:
            camp.status = "finished"
            _event(s, f"Campagne « {camp.name} » terminée", entity="campaign", entity_id=camp.id)


def _recheck(s: Session, enr: Enrollment, contact: Contact) -> str | None:
    """Raison de NE PAS envoyer, ou None si tout va bien (§6.6, étape 2)."""
    camp = s.get(Campaign, enr.campaign_id)
    prospection = ss.is_prospection(s.get(Sequence, camp.sequence_id) if camp else None)
    from app.campaigns_service import status_allows
    if not status_allows(contact, prospection, bool(camp and camp.direct)):
        return f"contact_{contact.global_status}"  # V2.23 : « A répondu » ne bloque que la prospection de groupe
    if contact.kind != "prospect" and prospection:  # devenu client / assureur / partenaire en cours de route (V2.3, V2.8)
        return f"kind_{contact.kind}"
    if suppression.is_suppressed_db(s, contact.email):
        return "suppressed"
    q = select(func.count(Message.id)).where(
        Message.contact_id == contact.id, Message.direction == "in",
        Message.kind.in_(STOPPING_KINDS), Message.received_at >= enr.created_at)
    if not prospection:  # V2.23 : la réponse sur un AUTRE dossier de la personne n'arrête pas celui-ci
        q = q.where((Message.enrollment_id.is_(None)) | (Message.enrollment_id == enr.id))
    stopping = s.scalar(q)
    if stopping:
        return "reply"
    return None


# ------------------------------------------------------------------- envoi

def _pick_due(s: Session, mb: Mailbox, now: datetime) -> Enrollment | None:
    return s.scalars(
        select(Enrollment).join(Campaign, Campaign.id == Enrollment.campaign_id)
        .where(Campaign.status == "active", Campaign.mailbox_id == mb.id,
               Enrollment.status.in_(DUE_STATUSES), Enrollment.next_due_at <= now)
        .order_by(Enrollment.next_due_at, Enrollment.id)
    ).first()


def _thread_chain(s: Session, enr: Enrollment) -> list[Message]:
    return list(s.scalars(select(Message).where(
        Message.enrollment_id == enr.id, Message.direction == "out", Message.sent_at.is_not(None))
        .order_by(Message.step_position)))


def tick(now: datetime | None = None, smtp_factory=None, imap_factory=None,
         rng: random.Random | None = None, sync=True, force_enrollment_id: int | None = None) -> TickResult:
    """Un passage du moteur. Appelé chaque minute par le planificateur.

    `force_enrollment_id` : bouton « envoyer maintenant » (respecte le mode test et
    la revérification, mais pas la fenêtre ni le délai entre deux envois)."""
    now = now or utcnow()
    smtp_factory = smtp_factory or transport.open_smtp
    imap_factory = imap_factory or transport.open_imap
    rng = rng or random.SystemRandom()
    if not _send_lock.acquire(blocking=False):
        return TickResult("busy", "Un envoi est déjà en cours")
    try:
        mark_stale_sending(now)
        # Lire la boîte AVANT d'envoyer : une réponse arrivée entre-temps doit arrêter la relance.
        if sync and not imap_sync.sync_if_stale(now):
            return TickResult("sync_failed", "Boîte de réception illisible : aucun envoi tant que les "
                                             "réponses ne peuvent pas être vérifiées")
        return _tick_locked(now, smtp_factory, imap_factory, rng, force_enrollment_id)
    finally:
        _send_lock.release()


def _tick_locked(now, smtp_factory, imap_factory, rng, force_id) -> TickResult:
    with get_session() as s:
        settings_store.set_(s, "engine_last_tick", _iso(now))
        finish_campaigns(s)
        s.commit()
        mb = get_primary(s)
        if mb is None:
            return TickResult("idle", "Boîte mail non configurée")

        if force_id is None:
            window = SendWindow.from_settings(s)
            if not window.is_open(now):
                return TickResult("closed", "Hors fenêtre d'envoi")
            c = counters(s, mb, now)
            if c["today"] >= c["daily_cap"]:
                return TickResult("cap_day", f"Plafond du jour atteint ({c['today']}/{c['daily_cap']})")
            if c["last_hour"] >= c["hourly_cap"]:
                return TickResult("cap_hour", f"Plafond horaire atteint ({c['last_hour']}/{c['hourly_cap']})")
            not_before = _from_iso(settings_store.get(s, "engine_next_allowed_at"))
            if not_before and now < not_before:
                return TickResult("gap", f"Prochain envoi possible à {to_local(not_before):%H:%M:%S}")
            enr = _pick_due(s, mb, now)
        else:
            enr = s.get(Enrollment, force_id)
            if enr is None or enr.status not in DUE_STATUSES:
                return TickResult("idle", "Inscription introuvable ou pas en attente d'envoi")
        if enr is None:
            return TickResult("idle", "Rien à envoyer")
        return _send(s, mb, enr, now, smtp_factory, imap_factory, rng)


def _send(s: Session, mb: Mailbox, enr: Enrollment, now, smtp_factory, imap_factory, rng) -> TickResult:
    camp = s.get(Campaign, enr.campaign_id)
    seq = s.get(Sequence, camp.sequence_id)
    contact = s.get(Contact, enr.contact_id)
    steps = ss.steps_for(s, seq, enr)  # V2.24 : seulement les emails choisis à l'envoi

    # 1) revérification
    reason = _recheck(s, enr, contact)
    if reason:
        status = {"contact_bounced": "bounced", "contact_unsubscribed": "unsubscribed",
                  "contact_replied": "replied", "reply": "replied"}.get(reason, "stopped")
        stop_enrollment(s, enr, status, reason)
        _event(s, f"Inscription n°{enr.id} arrêtée avant envoi ({reason})", entity_id=enr.id)
        s.commit()
        return TickResult("stopped", reason, enr.id)
    if enr.current_step > len(steps):
        stop_enrollment(s, enr, "completed", None)
        s.commit()
        return TickResult("idle", "Séquence déjà terminée", enr.id)

    # 2) rendu (le même que l'aperçu)
    step = steps[enr.current_step - 1]
    chain = _thread_chain(s, enr)
    ctx = ss.build_context(s, contact)
    unsubscribe = ss.unsubscribe_for(s, seq)
    if chain:
        first_subject = chain[0].subject
    else:
        # Étape 1 sautée : la relance « Re: » reprend l'objet que l'étape 1 aurait eu.
        first_subject = ss.compose_step(ctx, steps[0], ss.variants_of(s, steps[0]), enr.variant_label,
                                        "", unsubscribe, (enr.overrides or {}).get("1")).subject
    composed = ss.compose_step(ctx, step, ss.variants_of(s, step), enr.variant_label, first_subject,
                               unsubscribe, (enr.overrides or {}).get(str(step.position)))  # V2.9
    if composed.problems:
        enr.status, enr.next_due_at = "error", None
        enr.last_error = "Email impossible à composer : " + " ; ".join(composed.problems)
        _event(s, f"Inscription n°{enr.id} : {enr.last_error}", "error", entity_id=enr.id)
        s.commit()
        return TickResult("error", enr.last_error, enr.id)

    password = credentials.get_password(mb.email)
    if not password:
        settings_store.set_(s, "engine_last_error", "Mot de passe de la boîte introuvable : ressaisissez-le dans Réglages.")
        s.commit()
        return TickResult("error", "mot de passe absent")

    # 3) destinataire : LE point où le mode test s'applique
    test_mode = bool(settings_store.get(s, "test_mode"))
    to_email = mb.email if test_mode else contact.email
    header_subject = compose.test_mode_subject(composed.subject, contact.email) if test_mode else composed.subject
    message_id = compose.new_message_id(mb.email)
    threaded = step.same_thread and bool(chain)
    refs = [m.message_id for m in chain] if threaded else []
    try:
        atts = attachments_service.of_step(s, step.id)  # V2.8
        extra = ((enr.overrides or {}).get(str(step.position)) or {}).get("attachment_ids") or []
        if extra:  # V2.14 : pièces ajoutées pour cette personne
            atts = atts + [a for a in attachments_service.get_many(s, extra) if a.id not in {x.id for x in atts}]
            attachments_service.check_total(atts)
        email_msg = compose.build_message(
            from_name=mb.display_name, from_email=mb.email, to_email=to_email, subject=header_subject,
            body=composed.body, message_id=message_id,
            in_reply_to=refs[-1] if refs else None, references=refs or None,
            list_unsubscribe=ss.is_prospection(seq), attachments=atts)
    except attachments_service.AttachmentError as exc:
        enr.status, enr.next_due_at, enr.last_error = "error", None, str(exc)
        _event(s, f"Inscription n°{enr.id} : {exc}", "error", entity_id=enr.id)
        s.commit()
        return TickResult("error", str(exc), enr.id)

    # 4) on écrit AVANT d'envoyer
    out = Message(enrollment_id=enr.id, contact_id=contact.id, direction="out", message_id=message_id, mailbox_id=mb.id,
                  to_email=to_email, test_mode=test_mode, in_reply_to=refs[-1] if refs else None,
                  references_header=" ".join(refs) or None, subject=composed.subject,
                  body_text=composed.body, step_position=step.position,
                  attachments=[a.filename for a in atts] or None)
    s.add(out)
    enr.status, enr.updated_at = "sending", now
    s.commit()

    # 5) envoi SMTP
    cfg = server_config(as_form_values(mb), password)
    try:
        with smtp_factory(cfg) as smtp:
            smtp.send_message(email_msg)
    except smtplib.SMTPAuthenticationError as exc:
        return _undo_global(s, enr, out, "Identifiant ou mot de passe refusé par le serveur SMTP.", exc)
    except smtplib.SMTPRecipientsRefused as exc:
        code, text = next(iter(exc.recipients.values()))
        if code >= 500 and not test_mode:
            return _hard_bounce_on_send(s, enr, out, contact, code, text)
        return _temporary_failure(s, enr, out, now, f"Destinataire refusé ({code})", rng, mb)
    except smtplib.SMTPResponseException as exc:
        if exc.smtp_code >= 500:
            return _permanent_failure(s, enr, out, f"Refus définitif du serveur ({exc.smtp_code}) : {exc.smtp_error!r}")
        return _temporary_failure(s, enr, out, now, f"Erreur temporaire ({exc.smtp_code})", rng, mb)
    except (smtplib.SMTPException, OSError, ssl.SSLError) as exc:
        return _temporary_failure(s, enr, out, now, f"{type(exc).__name__} : {exc}", rng, mb)

    # 6) succès : on avance dans la séquence
    out.sent_at = now
    enr.attempts, enr.last_error = 0, None
    if step.position == 1:
        enr.thread_root_message_id = message_id
    enr.current_step += 1
    if enr.current_step <= len(steps):
        nxt = steps[enr.current_step - 1]
        # Échéance calculée depuis l'envoi RÉEL (§6.6 « rattrapage »).
        enr.next_due_at = SendWindow.from_settings(s).step_due(now, nxt)
        enr.status = "waiting"
    else:
        enr.status, enr.next_due_at = "completed", None
    gap = rng.randint(mb.min_gap_s, max(mb.min_gap_s, mb.max_gap_s))
    settings_store.set_(s, "engine_next_allowed_at", _iso(now + timedelta(seconds=gap)))
    settings_store.set_(s, "engine_last_error", "")
    _event(s, f"Étape {step.position} envoyée à {to_email}"
              + (f" (mode test, destinataire réel {contact.email})" if test_mode else ""), entity_id=enr.id)
    s.commit()

    # 7) copie dans « Envoyés » : un échec ne bloque jamais l'envoi
    if mb.sent_folder:  # V2.20 : en cas d'échec, copie mise en file et réessayée toutes les 5 minutes
        err = sent_copy.copy_or_queue(cfg, mb.sent_folder, email_msg.as_bytes(), now, imap_factory)
        if err:
            _event(s, f"Copie dans « {mb.sent_folder} » reportée (nouvel essai dans 5 minutes) : {err}", "warning", entity_id=enr.id)
            s.commit()
    return TickResult("sent", f"Étape {step.position} → {to_email}", enr.id)


def _quote_mailbox(name: str) -> str:
    """imaplib n'entoure pas les noms de dossier de guillemets : « Sent Items » échouerait."""
    return '"' + name.replace("\\", "\\\\").replace('"', '\\"') + '"'


# -------------------------------------------------------------- échecs SMTP

def _undo_global(s, enr, out, text, exc) -> TickResult:
    """Erreur qui concerne la boîte, pas ce contact : on annule et on prévient."""
    s.delete(out)
    enr.status = _back_status(enr)
    settings_store.set_(s, "engine_last_error", text)
    _event(s, f"Envoi suspendu : {text}", "error", entity="engine")
    s.commit()
    return TickResult("error", text, enr.id)


def _temporary_failure(s, enr, out, now, text, rng, mb) -> TickResult:
    s.delete(out)  # pas parti : on retire la trace « en cours »
    enr.attempts += 1
    enr.last_error = text
    if enr.attempts > len(RETRY_DELAYS):
        enr.status, enr.next_due_at = "error", None
        _event(s, f"Inscription n°{enr.id} en erreur après {len(RETRY_DELAYS)} nouvelles tentatives : {text}",
               "error", entity_id=enr.id)
        result = TickResult("failed", text, enr.id)
    else:
        enr.status = _back_status(enr)
        enr.next_due_at = now + RETRY_DELAYS[enr.attempts - 1]
        _event(s, f"Inscription n°{enr.id} : échec temporaire ({text}), nouvel essai à "
                  f"{to_local(enr.next_due_at):%H:%M}", "warning", entity_id=enr.id)
        result = TickResult("retry", text, enr.id)
    settings_store.set_(s, "engine_next_allowed_at", _iso(now + timedelta(seconds=mb.min_gap_s)))
    s.commit()
    return result


def _permanent_failure(s, enr, out, text) -> TickResult:
    s.delete(out)
    enr.status, enr.next_due_at, enr.last_error = "error", None, text
    _event(s, f"Inscription n°{enr.id} : {text}", "error", entity_id=enr.id)
    s.commit()
    return TickResult("failed", text, enr.id)


def _hard_bounce_on_send(s, enr, out, contact, code, text) -> TickResult:
    """5xx sur le destinataire = adresse invalide : rebond définitif (§6.6)."""
    s.delete(out)
    contact.global_status = "bounced"
    for other in s.scalars(select(Enrollment).where(Enrollment.contact_id == contact.id,
                                                   Enrollment.status.in_(OPEN_STATUSES))):
        stop_enrollment(s, other, "bounced", "bounce_hard")
    s.add(Message(contact_id=contact.id, enrollment_id=enr.id, direction="in", kind="bounce_hard", mailbox_id=out.mailbox_id,
                  subject=f"Refus SMTP {code}", body_text=text.decode("utf-8", "replace")
                  if isinstance(text, bytes) else str(text), received_at=utcnow()))
    _event(s, f"Adresse refusée par le serveur ({code}) : contact passé en rebond", "warning",
           entity="contact", entity_id=contact.id)
    s.commit()
    return TickResult("failed", f"Rebond définitif ({code})", enr.id)


# ------------------------------------------------------- actions « à vérifier »

def confirm_sent(enrollment_id: int, now: datetime | None = None) -> bool:
    """L'utilisateur a vu l'email dans ses Envoyés : on le considère comme parti."""
    now = now or utcnow()
    with get_session() as s:
        enr = s.get(Enrollment, enrollment_id)
        if enr is None or enr.status != "needs_review":
            return False
        out = s.scalars(select(Message).where(Message.enrollment_id == enr.id, Message.direction == "out",
                                              Message.sent_at.is_(None))).first()
        camp = s.get(Campaign, enr.campaign_id)
        steps = ss.steps_for(s, s.get(Sequence, camp.sequence_id), enr)
        sent_at = enr.updated_at or now
        if out is not None:
            out.sent_at = sent_at
            if out.step_position == 1:
                enr.thread_root_message_id = out.message_id
        enr.current_step += 1
        enr.last_error = None
        if enr.current_step <= len(steps):
            nxt = steps[enr.current_step - 1]
            enr.next_due_at = SendWindow.from_settings(s).step_due(max(sent_at, now), nxt)
            enr.status = "waiting"
        else:
            enr.status, enr.next_due_at = "completed", None
        _event(s, f"Inscription n°{enr.id} : envoi confirmé manuellement", entity_id=enr.id)
        s.commit()
        return True


def retry_now(enrollment_id: int, now: datetime | None = None) -> bool:
    """« Renvoyer » : l'email n'est pas dans les Envoyés, on le remet dans la file."""
    now = now or utcnow()
    with get_session() as s:
        enr = s.get(Enrollment, enrollment_id)
        if enr is None or enr.status not in ("needs_review", "error"):
            return False
        for out in s.scalars(select(Message).where(Message.enrollment_id == enr.id, Message.direction == "out",
                                                  Message.sent_at.is_(None))):
            s.delete(out)
        enr.status, enr.next_due_at, enr.attempts, enr.last_error = _back_status(enr), now, 0, None
        _event(s, f"Inscription n°{enr.id} remise dans la file d'envoi", entity_id=enr.id)
        s.commit()
        return True

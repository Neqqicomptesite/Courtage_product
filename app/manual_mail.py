"""Écrire un email depuis l'application (V2.4) : réponse à un email de la boîte, ou nouveau
message à un contact. Choix d'Omar : « écrire dans l'app » plutôt qu'ouvrir sa messagerie.

- Même chemin que les séquences : SMTP de la boîte, copie dans « Envoyés », et le mode test
  s'applique ici aussi (l'email part chez Omar, objet préfixé [TEST → destinataire]).
- L'email garde le fil de la conversation (In-Reply-To / References) : chez le destinataire,
  il s'affiche sous le message auquel il répond.
- Il est enregistré dans l'historique du contact (et donc de son entreprise), sans compter
  dans les statistiques ni les plafonds des campagnes (aucune inscription liée).
- Pas de ligne de désinscription ni d'en-tête List-Unsubscribe : c'est un échange personnel.
"""
from __future__ import annotations

import imaplib
import smtplib
import ssl
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import attachments_service, credentials, mailbox_browser, settings_store, suppression
from app.importer import EMAIL_RE
from app.mail import compose, transport
from app.mailbox_service import as_form_values, get_primary, server_config
from app.models import Contact, EventLog, Message
from app.timeutil import utcnow


class SendRefused(ValueError):
    def __init__(self, errors: dict[str, str], confirm: str | None = None):
        super().__init__(" ".join(errors.values()) or (confirm or ""))
        self.errors, self.confirm = errors, confirm


@dataclass
class Draft:
    to: list[str]
    subject: str
    body: str
    cc: list[str] = field(default_factory=list)
    in_reply_to: str | None = None
    references: list[str] = field(default_factory=list)
    signature: bool = True
    force: bool = False  # envoyer malgré la liste d'exclusion (confirmé par Omar)
    attachment_ids: list[int] = field(default_factory=list)  # V2.8


def _split(value) -> list[str]:
    if isinstance(value, list):
        items = value
    else:
        items = str(value or "").replace(";", ",").split(",")
    return [x.strip().lower() for x in items if x and x.strip()]


def draft_from(body: dict) -> Draft:
    return Draft(to=_split(body.get("to")), cc=_split(body.get("cc")), subject=str(body.get("subject") or "").strip(),
                 body=str(body.get("body") or "").replace("\r\n", "\n").rstrip(),
                 in_reply_to=body.get("in_reply_to") or None, references=[r for r in body.get("references") or [] if r],
                 signature=bool(body.get("signature", True)), force=bool(body.get("force")),
                 attachment_ids=[int(i) for i in body.get("attachment_ids") or []])


def validate(s: Session, d: Draft) -> None:
    errors = {}
    if not d.to:
        errors["to"] = "Indiquez au moins un destinataire."
    elif bad := [a for a in d.to + d.cc if not EMAIL_RE.match(a)]:
        errors["to"] = "Adresse invalide : " + ", ".join(bad)
    # V2.21 : un email sans objet est permis (l'écran demande confirmation avant, comme Gmail)
    if not d.body.strip():
        errors["body"] = "Le message est vide."
    if errors:
        raise SendRefused(errors)
    supp = suppression.suppressed_keys(s)
    blocked = [a for a in d.to + d.cc if suppression.is_suppressed(a, supp)]
    if blocked and not d.force:
        raise SendRefused({}, confirm=f"{', '.join(blocked)} : sur la liste d'exclusion (demande STOP, effacement ou "
                                      "exclusion manuelle). Envoyer quand même ce message personnel ?")


def send(s: Session, d: Draft, now: datetime | None = None, smtp_factory=None, imap_factory=None) -> Message:
    now = now or utcnow()
    validate(s, d)
    mb = get_primary(s)
    if mb is None:
        raise SendRefused({"to": "Aucune boîte mail configurée : renseignez-la dans Réglages."})
    password = credentials.get_password(mb.email)
    if not password:
        raise SendRefused({"to": "Mot de passe de la boîte introuvable : ressaisissez-le dans Réglages."})

    test_mode = bool(settings_store.get(s, "test_mode"))
    body = d.body
    if d.signature and (mb.signature or "").strip():
        body = f"{body}\n\n{mb.signature.strip()}"
    real = ", ".join(d.to)
    try:
        atts = attachments_service.get_many(s, d.attachment_ids)
        attachments_service.check_total(atts)
    except attachments_service.AttachmentError as exc:
        raise SendRefused({"attachments": str(exc)}) from None
    message_id = compose.new_message_id(mb.email)
    msg = compose.build_message(
        from_name=mb.display_name, from_email=mb.email, to_email=mb.email if test_mode else real,
        subject=compose.test_mode_subject(d.subject, real) if test_mode else d.subject, body=body,
        message_id=message_id, in_reply_to=d.in_reply_to, references=d.references or None, list_unsubscribe=False,
        attachments=atts)
    if d.cc and not test_mode:
        msg["Cc"] = ", ".join(d.cc)

    cfg = server_config(as_form_values(mb), password)
    try:
        with (smtp_factory or transport.open_smtp)(cfg) as smtp:
            smtp.send_message(msg)
    except (smtplib.SMTPException, OSError, ssl.SSLError) as exc:
        raise SendRefused({"to": transport.explain_error(exc, "SMTP", cfg.smtp_host, cfg.smtp_port)}) from None

    contact = s.scalars(select(Contact).where(Contact.email == d.to[0])).first()
    out = Message(contact_id=contact.id if contact else None, direction="out", message_id=message_id, mailbox_id=mb.id,
                  to_email=mb.email if test_mode else real, test_mode=test_mode, in_reply_to=d.in_reply_to,
                  references_header=" ".join(d.references) or None, subject=d.subject, body_text=body, sent_at=now,
                  attachments=[a.filename for a in atts] or None)
    s.add(out)
    s.add(EventLog(level="info", entity="contact" if contact else "mail", entity_id=contact.id if contact else None,
                   text=f"Email écrit à {real}" + (" (mode test : parti vers votre adresse)" if test_mode else "")))
    s.commit()

    if mb.sent_folder:  # copie dans « Envoyés » : un échec ne remet pas l'envoi en cause (V2.20 : réessayée)
        from app import sent_copy
        err = sent_copy.copy_or_queue(cfg, mb.sent_folder, msg.as_bytes(), now, imap_factory or transport.open_imap)
        if err:
            s.add(EventLog(level="warning", entity="mail",
                           text=f"Copie dans « {mb.sent_folder} » reportée (nouvel essai dans 5 minutes) : {err}"))
            s.commit()
        mailbox_browser.invalidate(mb.sent_folder)
    return out

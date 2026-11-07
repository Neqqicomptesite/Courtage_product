"""Construction des emails sortants (§6.6, étape 3).

Tout email envoyé par l'app passe par build_message() : c'est l'unique endroit
où l'on fixe les en-têtes. Les relances « dans le même fil » utilisent
In-Reply-To et References : c'est ce qui permet à Outlook ou Gmail d'afficher la
relance sous le premier message, comme si vous aviez cliqué sur « Répondre ».
"""
from __future__ import annotations

from email.message import EmailMessage
from email.utils import formataddr, formatdate, make_msgid


def new_message_id(sender_email: str) -> str:
    return make_msgid(domain=sender_email.rsplit("@", 1)[-1])


def build_message(*, from_name: str, from_email: str, to_email: str, subject: str, body: str,
                  message_id: str, in_reply_to: str | None = None,
                  references: list[str] | None = None, list_unsubscribe: bool = True,
                  attachments=None, session=None) -> EmailMessage:
    msg = EmailMessage()
    msg["From"] = formataddr((from_name, from_email))
    msg["To"] = to_email
    msg["Subject"] = subject
    msg["Date"] = formatdate(localtime=False)
    msg["Message-ID"] = message_id
    if in_reply_to:
        msg["In-Reply-To"] = in_reply_to
    if references:
        msg["References"] = " ".join(references)
    # Désinscription en un clic dans les messageries qui la proposent (§6.6).
    # Pas pour un email écrit à la main (V2.4) : c'est un échange personnel, pas une campagne.
    if list_unsubscribe:
        msg["List-Unsubscribe"] = f"<mailto:{from_email}?subject=STOP>"
    # Texte brut uniquement, UTF-8, encodage « quoted-printable » : lisible, accents préservés.
    msg.set_content(body, subtype="plain", charset="utf-8", cte="quoted-printable")
    if attachments:  # V2.8 : liste d'objets Attachment
        from app import attachments_service
        attachments_service.attach(msg, attachments)
    return msg


def test_mode_subject(subject: str, real_recipient: str) -> str:
    """Mode test : l'email part chez Omar, l'objet rappelle à qui il était destiné."""
    return f"[TEST → {real_recipient}] {subject}"


def preview_subject(subject: str, real_recipient: str) -> str:
    return f"[APERÇU → {real_recipient}] {subject}"

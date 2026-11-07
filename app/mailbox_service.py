"""Lecture / enregistrement de la boîte mail (une seule en v1, table prête pour plusieurs)."""
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import credentials
from app.mail.transport import ServerConfig
from app.models import Mailbox

DEFAULT_MAILBOX = {
    "display_name": "",   # kit de partage (V2.6) : chaque collègue saisit sa propre boîte
    "email": "",
    "smtp_host": "",
    "smtp_port": 465,
    "smtp_security": "ssl",
    "imap_host": "",
    "imap_port": 993,
    "username": "",
    "sent_folder": None,
    "watched_folders": ["INBOX"],
    "signature": "",
    "daily_cap": 25,
    "hourly_cap": 10,
    "min_gap_s": 90,
    "max_gap_s": 240,
}


def get_primary(session: Session) -> Mailbox | None:
    """La boîte de l'employé en cours (V3) ; en poste unique, la seule boîte."""
    from app.current import user_id
    uid = user_id()
    if uid is not None:
        return session.scalars(select(Mailbox).where(Mailbox.user_id == uid)).first()
    return session.scalars(select(Mailbox).order_by(Mailbox.id)).first()


def as_form_values(mb: Mailbox | None) -> dict:
    if mb is None:
        return dict(DEFAULT_MAILBOX)
    return {k: getattr(mb, k) for k in DEFAULT_MAILBOX}


def server_config(values: dict, password: str) -> ServerConfig:
    return ServerConfig(
        email=values["email"], display_name=values["display_name"],
        smtp_host=values["smtp_host"], smtp_port=int(values["smtp_port"]),
        smtp_security=values["smtp_security"],
        imap_host=values["imap_host"], imap_port=int(values["imap_port"]),
        username=values["username"], password=password,
    )


def save(session: Session, values: dict, new_password: str | None) -> Mailbox:
    """Enregistre la boîte. Le mot de passe va dans keyring, jamais dans la base.

    On écrit le mot de passe AVANT de valider la transaction : si keyring
    échoue, la boîte n'est pas enregistrée à moitié.
    """
    mb = get_primary(session)
    old_email = mb.email if mb else None
    if mb is None:
        from app.current import user_id
        mb = Mailbox(**{k: values[k] for k in DEFAULT_MAILBOX}, user_id=user_id())
        session.add(mb)
    else:
        for k in DEFAULT_MAILBOX:
            setattr(mb, k, values[k])

    if new_password:
        credentials.set_password(values["email"], new_password)
    elif old_email and old_email.lower() != values["email"].lower():
        # L'adresse a changé : on déplace le mot de passe existant vers la nouvelle entrée.
        pw = credentials.get_password(old_email)
        if pw:
            credentials.set_password(values["email"], pw)
            credentials.delete_password(old_email)
    session.flush()
    return mb

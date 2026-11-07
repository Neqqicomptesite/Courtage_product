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


def as_form_values(mb: Mailbox | None, session: Session | None = None) -> dict:
    if mb is None:
        return _new_colleague_defaults(session) if session is not None else dict(DEFAULT_MAILBOX)
    return {k: getattr(mb, k) for k in DEFAULT_MAILBOX}


def _new_colleague_defaults(session: Session) -> dict:
    """V3 : un collègue qui n'a pas encore réglé sa boîte trouve le formulaire pré-rempli :
    son nom et son email de connexion, et les serveurs (hôtes, ports, sécurité, dossiers)
    de la boîte de l'administrateur, qui marchent depuis le serveur (envoi en 587, le 465
    étant bloqué chez l'hébergeur). Jamais de mot de passe."""
    values = dict(DEFAULT_MAILBOX)
    from app.current import user_id
    uid = user_id()
    if uid is None:
        return values
    from app.models import AppUser
    me = session.get(AppUser, uid)
    ref = session.scalars(select(Mailbox).join(AppUser, AppUser.id == Mailbox.user_id)
                          .where(AppUser.role == "admin", AppUser.active.is_(True)).order_by(Mailbox.id)).first()
    if ref is not None:
        for k in ("smtp_host", "smtp_port", "smtp_security", "imap_host", "imap_port", "sent_folder", "watched_folders"):
            values[k] = getattr(ref, k)
    if me is not None:
        values.update(email=me.email, username=me.email, display_name=me.full_name or values.get("display_name", ""))
    return values


def server_config(values: dict, password: str) -> ServerConfig:
    return ServerConfig(
        email=values["email"], display_name=values["display_name"],
        smtp_host=values["smtp_host"], smtp_port=int(values["smtp_port"]),
        smtp_security=values["smtp_security"],
        imap_host=values["imap_host"], imap_port=int(values["imap_port"]),
        username=values["username"], password=password,
    )


class MailboxTaken(ValueError):
    """V3 : cette adresse est déjà la boîte d'un collègue."""


def save(session: Session, values: dict, new_password: str | None) -> Mailbox:
    """Enregistre la boîte. Le mot de passe va dans keyring, jamais dans la base.

    On écrit le mot de passe AVANT de valider la transaction : si keyring
    échoue, la boîte n'est pas enregistrée à moitié.
    """
    mb = get_primary(session)
    old_email = mb.email if mb else None
    # V3 : vérifié AVANT d'écrire le mot de passe (rangé sous l'adresse de la boîte) : sinon
    # saisir l'adresse d'un collègue remplaçait son mot de passe et bloquait ses envois.
    from sqlalchemy import func, select
    other = session.scalar(select(Mailbox.id).execution_options(oddo_all=True)
                           .where(func.lower(Mailbox.email) == values["email"].strip().lower(),
                                  Mailbox.id != (mb.id if mb else -1)))
    if other is not None:
        raise MailboxTaken("Cette adresse est déjà la boîte mail d'un collègue : chacun utilise la sienne.")
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

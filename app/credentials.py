"""Mot de passe de la boîte mail, stocké dans le coffre du système.

Sous Windows, `keyring` utilise le « Gestionnaire d'identification »
(Panneau de configuration > Gestionnaire d'identification > Informations
d'identification Windows, entrée « ODDO-Sequences »). Le mot de passe n'est
jamais écrit dans la base ni dans un fichier du projet.

Si aucun coffre n'est disponible, on ÉCHOUE avec un message clair plutôt que
de se rabattre sur un stockage en clair.
"""
import keyring
from keyring.errors import KeyringError, NoKeyringError, PasswordDeleteError

from app.logging_setup import register_secret

SERVICE = "ODDO-Sequences"


class CredentialError(RuntimeError):
    pass


def _account(email: str) -> str:
    return email.strip().lower()


# --- V3 : sur le serveur, pas de Gestionnaire Windows : coffre chiffré dans la base -----
def _server_box():
    """Coffre du serveur : chiffrement Fernet avec la clé ODDO_SECRET_KEY (variable
    d'environnement du serveur, jamais dans la base ni dans le code). None en poste unique."""
    import os
    from app.paths import is_server_mode
    if not is_server_mode():
        return None
    key = os.environ.get("ODDO_SECRET_KEY", "").strip()
    if not key:
        raise CredentialError("Clé de chiffrement du serveur absente (ODDO_SECRET_KEY).")
    from cryptography.fernet import Fernet
    return Fernet(key.encode())


def _server_set(box, account: str, password: str) -> None:
    from app.db import get_session
    from app.models import Secret
    with get_session() as s, s.begin():
        row = s.get(Secret, (SERVICE, account))
        token = box.encrypt(password.encode()).decode()
        if row is None:
            s.add(Secret(service=SERVICE, account=account, value=token))
        else:
            row.value = token


def _server_get(box, account: str) -> str | None:
    from cryptography.fernet import InvalidToken
    from app.db import get_session
    from app.models import Secret
    with get_session() as s:
        row = s.get(Secret, (SERVICE, account))
        if row is None:
            return None
        try:
            return box.decrypt(row.value.encode()).decode()
        except InvalidToken as exc:
            raise CredentialError("Mot de passe illisible : la clé du serveur a changé.") from exc


def set_password(email: str, password: str) -> None:
    box = _server_box()
    if box is not None:
        _server_set(box, _account(email), password)
        register_secret(password)
        return
    try:
        keyring.set_password(SERVICE, _account(email), password)
    except (NoKeyringError, KeyringError) as exc:
        raise CredentialError(
            "Impossible d'enregistrer le mot de passe dans le Gestionnaire "
            f"d'identification Windows ({type(exc).__name__})."
        ) from exc
    register_secret(password)


def get_password(email: str) -> str | None:
    box = _server_box()
    if box is not None:
        pw = _server_get(box, _account(email))
        register_secret(pw)
        return pw
    try:
        pw = keyring.get_password(SERVICE, _account(email))
    except (NoKeyringError, KeyringError) as exc:
        raise CredentialError(
            f"Impossible de lire le Gestionnaire d'identification ({type(exc).__name__})."
        ) from exc
    register_secret(pw)
    return pw


def has_password(email: str) -> bool:
    try:
        return bool(get_password(email))
    except CredentialError:
        return False


def delete_password(email: str) -> None:
    if _server_box() is not None:
        from sqlalchemy import delete
        from app.db import get_session
        from app.models import Secret
        with get_session() as s, s.begin():
            s.execute(delete(Secret).where(Secret.service == SERVICE, Secret.account == _account(email)))
        return
    try:
        keyring.delete_password(SERVICE, _account(email))
    except PasswordDeleteError:
        pass

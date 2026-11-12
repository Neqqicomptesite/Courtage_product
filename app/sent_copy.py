"""Copie des emails envoyés dans le dossier « Envoyés » du serveur (V2.20 : file d'attente).

L'envoi (SMTP) et la copie (IMAP APPEND) sont deux opérations séparées. Si la copie échoue
(coupure réseau d'une seconde, serveur IMAP surchargé), l'email est bien parti mais
n'apparaîtrait pas dans « Envoyés » d'Outlook ou du webmail. On le garde donc dans
data/envoyes_a_copier/ et on réessaie toutes les 5 minutes, jusqu'à 7 jours.
"""
from __future__ import annotations

import imaplib
import logging
import re
import time
from datetime import datetime
from pathlib import Path

from app.paths import data_dir

log = logging.getLogger(__name__)
MAX_AGE_S = 7 * 24 * 3600


def queue_dir(owner: str | None = None) -> Path:
    """V3.8 : une file PAR BOÎTE. Avant, sur le serveur, la file était commune à toute l'équipe :
    une copie en attente d'un employé aurait pu être rangée dans la boîte d'un autre."""
    d = data_dir() / "envoyes_a_copier"
    if owner:
        d = d / re.sub(r"[^a-z0-9._@-]", "_", owner.lower())
    d.mkdir(parents=True, exist_ok=True)
    return d


def _owner(cfg) -> str | None:
    return getattr(cfg, "username", None) or None


def _sender(raw: bytes) -> str:
    """Adresse de l'expéditeur d'un email en attente (pour les fichiers d'avant la V3.8)."""
    from email import message_from_bytes
    from email.utils import parseaddr
    try:
        return parseaddr(message_from_bytes(raw).get("From", ""))[1].lower()
    except Exception:  # noqa: BLE001
        return ""


def safe_folder(folder: str | None) -> str | None:
    """V3.8 : jamais de copie « Envoyés » dans la boîte de réception (elle y apparaîtrait comme un
    email reçu de soi-même). Un réglage « INBOX » est ignoré : pas de copie plutôt qu'une fausse."""
    if not folder or folder.strip().upper() == "INBOX":
        return None
    return folder


def _quote(name: str) -> str:
    return '"' + name.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _append(conn, folder: str, raw: bytes, when: datetime) -> None:
    typ, data = conn.append(_quote(folder), "(\\Seen)", imaplib.Time2Internaldate(when), raw)
    if typ != "OK":
        raise imaplib.IMAP4.error(f"APPEND refusé : {data!r}")


def copy_or_queue(cfg, folder: str, raw: bytes, when: datetime, imap_factory) -> str | None:
    """Copie tout de suite ; en cas d'échec, met en file et renvoie le message d'erreur."""
    folder = safe_folder(folder)
    if folder is None:
        return "dossier des envoyés réglé sur la boîte de réception : copie non faite (Réglages → Boîte mail)"
    try:
        conn = imap_factory(cfg)
        try:
            _append(conn, folder, raw, when)
        finally:
            try:
                conn.logout()
            except Exception:  # noqa: BLE001
                pass
        return None
    except Exception as exc:  # noqa: BLE001
        name = f"{int(when.timestamp())}-{time.time_ns()}.eml"
        (queue_dir(_owner(cfg)) / name).write_bytes(raw)
        return str(exc)


def pending(owner: str | None = None) -> list[Path]:
    """Copies en attente de cette boîte ; plus, pour les anciens fichiers communs (avant la V3.8),
    seulement ceux dont elle est l'expéditeur."""
    if not owner:  # poste unique (ou vue d'ensemble) : toutes les copies en attente
        return sorted(queue_dir().rglob("*.eml"))
    mine = sorted(queue_dir(owner).glob("*.eml"))
    legacy = [f for f in sorted(queue_dir().glob("*.eml")) if _sender(f.read_bytes()) == owner.lower()]
    return mine + legacy


def flush(cfg, folder: str, imap_factory) -> int:
    """Réessaie les copies en attente. Renvoie le nombre de copies faites."""
    folder = safe_folder(folder)
    files = pending(_owner(cfg))
    if not files or not folder:
        return 0
    done = 0
    try:
        conn = imap_factory(cfg)
    except Exception:  # noqa: BLE001 – serveur encore injoignable : on réessaiera
        return 0
    try:
        for f in files:
            try:
                when = datetime.fromtimestamp(int(f.name.split("-", 1)[0])).astimezone()
            except ValueError:
                when = datetime.now().astimezone()
            if time.time() - when.timestamp() > MAX_AGE_S:
                log.warning("Copie dans « Envoyés » abandonnée après 7 jours : %s", f.name)
                f.unlink(missing_ok=True)
                continue
            try:
                _append(conn, folder, f.read_bytes(), when)
            except Exception:  # noqa: BLE001
                break  # on garde l'ordre ; nouvel essai au prochain passage
            f.unlink(missing_ok=True)
            done += 1
    finally:
        try:
            conn.logout()
        except Exception:  # noqa: BLE001
            pass
    if done:
        log.info("%d copie(s) en attente rangée(s) dans « %s »", done, folder)
    return done

"""Copie des emails envoyés dans le dossier « Envoyés » du serveur (V2.20 : file d'attente).

L'envoi (SMTP) et la copie (IMAP APPEND) sont deux opérations séparées. Si la copie échoue
(coupure réseau d'une seconde, serveur IMAP surchargé), l'email est bien parti mais
n'apparaîtrait pas dans « Envoyés » d'Outlook ou du webmail. On le garde donc dans
data/envoyes_a_copier/ et on réessaie toutes les 5 minutes, jusqu'à 7 jours.
"""
from __future__ import annotations

import imaplib
import logging
import time
from datetime import datetime
from pathlib import Path

from app.paths import data_dir

log = logging.getLogger(__name__)
MAX_AGE_S = 7 * 24 * 3600


def queue_dir() -> Path:
    d = data_dir() / "envoyes_a_copier"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _quote(name: str) -> str:
    return '"' + name.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _append(conn, folder: str, raw: bytes, when: datetime) -> None:
    typ, data = conn.append(_quote(folder), "(\\Seen)", imaplib.Time2Internaldate(when), raw)
    if typ != "OK":
        raise imaplib.IMAP4.error(f"APPEND refusé : {data!r}")


def copy_or_queue(cfg, folder: str, raw: bytes, when: datetime, imap_factory) -> str | None:
    """Copie tout de suite ; en cas d'échec, met en file et renvoie le message d'erreur."""
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
        (queue_dir() / name).write_bytes(raw)
        return str(exc)


def pending() -> list[Path]:
    return sorted(queue_dir().glob("*.eml"))


def flush(cfg, folder: str, imap_factory) -> int:
    """Réessaie les copies en attente. Renvoie le nombre de copies faites."""
    files = pending()
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

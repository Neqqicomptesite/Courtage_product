"""Journaux applicatifs avec rotation, et masquage des secrets.

Deux protections complémentaires :
1. on n'active JAMAIS le mode debug de smtplib/imaplib (il afficherait les
   échanges bruts, dont les commandes AUTH/LOGIN) ;
2. un filtre remplace dans chaque ligne de journal tout mot de passe connu et
   toute commande AUTH/LOGIN par « *** », au cas où une exception le contiendrait.
"""
import logging
import re
from logging.handlers import RotatingFileHandler

from app.paths import logs_dir

_known_secrets: set[str] = set()
_AUTH_PATTERNS = [
    re.compile(r"(AUTH\s+\S+)\s+\S+", re.IGNORECASE),
    re.compile(r"(\bLOGIN)\s+\S+\s+\S+", re.IGNORECASE),
]


def register_secret(value: str | None) -> None:
    if value and len(value) >= 3:
        _known_secrets.add(value)


def redact(text: str) -> str:
    for secret in _known_secrets:
        text = text.replace(secret, "***")
    for pat in _AUTH_PATTERNS:
        text = pat.sub(r"\1 ***", text)
    return text


class RedactingFormatter(logging.Formatter):
    """Masque la ligne ENTIÈRE une fois formatée, y compris les tracebacks d'exception."""

    def format(self, record: logging.LogRecord) -> str:
        return redact(super().format(record))


def setup_logging() -> None:
    root = logging.getLogger()
    if any(getattr(h, "_oddo", False) for h in root.handlers):
        return  # déjà configuré
    logs_dir().mkdir(parents=True, exist_ok=True)
    # 1 fichier courant + 4 archives = 5 fichiers de 2 Mo (cahier des charges §3)
    fh = RotatingFileHandler(logs_dir() / "app.log", maxBytes=2 * 1024 * 1024,
                             backupCount=4, encoding="utf-8")
    fh._oddo = True
    fh.setFormatter(RedactingFormatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    sh = logging.StreamHandler()
    sh._oddo = True
    sh.setFormatter(RedactingFormatter("%(asctime)s %(levelname)s %(message)s"))
    root.addHandler(fh)
    root.addHandler(sh)
    root.setLevel(logging.INFO)
    # APScheduler écrit 2 lignes par minute (« job exécuté ») : inutile dans le journal.
    logging.getLogger("apscheduler").setLevel(logging.WARNING)

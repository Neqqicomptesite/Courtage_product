"""Connexions SMTP (envoi) et IMAP (lecture), et le « test de connexion ».

Points importants :
- Les certificats TLS sont TOUJOURS vérifiés (ssl.create_default_context()).
  Si le nom du serveur ne correspond pas au certificat, l'erreur est expliquée
  à l'utilisateur au lieu d'être contournée.
- Le mode debug de smtplib/imaplib n'est jamais activé (il afficherait le mot de passe).
- Chaque connexion a un délai d'attente : un serveur muet ne doit pas bloquer l'app.
"""
from __future__ import annotations

import imaplib
import os
import re
import smtplib
import socket
import ssl
from dataclasses import dataclass, field
from email.message import EmailMessage
from email.utils import formataddr, formatdate, make_msgid

from app.mail import imap_utf7

TIMEOUT_S = 30


@dataclass
class ServerConfig:
    email: str
    display_name: str
    smtp_host: str
    smtp_port: int
    smtp_security: str  # "ssl" (port 465) ou "starttls" (port 587)
    imap_host: str
    imap_port: int
    username: str
    password: str = field(repr=False)  # repr=False : jamais affiché par print()/logs

    @property
    def domain(self) -> str:
        return self.email.rsplit("@", 1)[-1]


def tls_context() -> ssl.SSLContext:
    """Contexte TLS standard : certificat vérifié, nom d'hôte vérifié.

    ODDO_EXTRA_CA_FILE (variable d'environnement, tests et bac à sable
    uniquement) ajoute une autorité de confiance SUPPLÉMENTAIRE : celle des
    faux serveurs locaux. Elle n'affaiblit pas la vérification des vrais serveurs.
    """
    ctx = ssl.create_default_context()
    extra = os.environ.get("ODDO_EXTRA_CA_FILE")
    if extra:
        ctx.load_verify_locations(cafile=extra)
    return ctx


def open_smtp(cfg: ServerConfig) -> smtplib.SMTP:
    if cfg.smtp_security == "ssl":
        server = smtplib.SMTP_SSL(cfg.smtp_host, cfg.smtp_port, timeout=TIMEOUT_S,
                                  context=tls_context())
    else:
        server = smtplib.SMTP(cfg.smtp_host, cfg.smtp_port, timeout=TIMEOUT_S)
    try:
        if cfg.smtp_security != "ssl":
            server.ehlo()
            server.starttls(context=tls_context())
            server.ehlo()
        server.login(cfg.username, cfg.password)
    except BaseException:
        # Sans ça, un mot de passe refusé laisserait la connexion ouverte
        # (le « with » de l'appelant n'a pas encore commencé).
        server.close()
        raise
    return server


class ImapAuthError(Exception):
    pass


def open_imap(cfg: ServerConfig) -> imaplib.IMAP4_SSL:
    conn = imaplib.IMAP4_SSL(cfg.imap_host, cfg.imap_port, ssl_context=tls_context(),
                             timeout=TIMEOUT_S)
    try:
        conn.login(cfg.username, cfg.password)
    except imaplib.IMAP4.error as exc:
        # Les serveurs formulent le refus différemment ; un échec de LOGIN est un refus d'identifiants.
        try:
            conn.shutdown()
        except Exception:  # noqa: BLE001
            pass
        raise ImapAuthError(str(exc)) from None
    return conn


# --- Dossiers IMAP ------------------------------------------------------------

@dataclass
class Folder:
    raw_name: str        # nom exact à utiliser dans les commandes IMAP
    display_name: str    # nom décodé pour l'affichage
    flags: list[str]

    @property
    def selectable(self) -> bool:
        return "\\noselect" not in [f.lower() for f in self.flags]


_LIST_RE = re.compile(r'^\((?P<flags>[^)]*)\)\s+(?P<delim>"(?:[^"\\]|\\.)*"|NIL)\s+(?P<name>.*)$')

# Noms courants quand le serveur n'annonce pas les attributs \Sent / \Junk (RFC 6154).
_SENT_GUESSES = ["sent", "inbox.sent", "sent items", "sent messages", "envoyés",
                 "éléments envoyés", "inbox.envoyés", "inbox.sent items"]
_JUNK_GUESSES = ["junk", "spam", "inbox.junk", "inbox.spam", "courrier indésirable",
                 "indésirables", "inbox.indésirables"]


def _unquote(s: str) -> str:
    s = s.strip()
    if len(s) >= 2 and s[0] == '"' and s[-1] == '"':
        return s[1:-1].replace('\\"', '"').replace("\\\\", "\\")
    return s


def parse_list_response(lines: list) -> list[Folder]:
    """Analyse la réponse brute de la commande IMAP LIST.

    imaplib renvoie soit des bytes (cas simple), soit un tuple
    (en-tête, nom) quand le serveur envoie le nom sous forme de « littéral ».
    """
    folders = []
    for item in lines:
        if item is None:
            continue
        if isinstance(item, tuple):
            header = item[0].decode("utf-8", "replace")
            literal_name = item[1].decode("utf-8", "replace")
            m = _LIST_RE.match(header.rsplit("{", 1)[0].strip() + " X")
            if not m:
                continue
            raw = literal_name
        else:
            m = _LIST_RE.match(item.decode("utf-8", "replace"))
            if not m:
                continue
            raw = _unquote(m.group("name"))
        flags = m.group("flags").split()
        folders.append(Folder(raw_name=raw, display_name=imap_utf7.decode(raw), flags=flags))
    return folders


def detect_special(folders: list[Folder], attribute: str, guesses: list[str]) -> str | None:
    """Trouve le dossier Envoyés (\\Sent) ou Spam (\\Junk) : attribut d'abord, nom ensuite."""
    for f in folders:
        if attribute.lower() in [x.lower() for x in f.flags]:
            return f.raw_name
    by_name = {f.display_name.lower(): f.raw_name for f in folders}
    for guess in guesses:
        if guess in by_name:
            return by_name[guess]
    return None


def list_folders(conn: imaplib.IMAP4) -> list[Folder]:
    typ, data = conn.list()
    if typ != "OK":
        raise imaplib.IMAP4.error(f"LIST refusé : {typ}")
    return [f for f in parse_list_response(data) if f.selectable]


# --- Messages d'erreur compréhensibles ------------------------------------------

def explain_error(exc: BaseException, service: str, host: str, port: int) -> str:
    if isinstance(exc, smtplib.SMTPAuthenticationError):
        return "Identifiant ou mot de passe refusé par le serveur SMTP."
    if isinstance(exc, ImapAuthError):
        return "Identifiant ou mot de passe refusé par le serveur IMAP."
    if isinstance(exc, ssl.SSLCertVerificationError):
        return ("Le certificat de sécurité du serveur ne correspond pas au nom "
                f"« {host} ». Utilisez le nom de serveur exact indiqué par Heberjahiz "
                "(souvent le nom du serveur d'hébergement plutôt que mail.votredomaine).")
    if isinstance(exc, ssl.SSLError):
        return (f"Échec de la connexion sécurisée sur le port {port}. Vérifiez le couple "
                "port / sécurité (465 = SSL, 587 = STARTTLS, 993 = IMAP SSL).")
    if isinstance(exc, socket.gaierror):
        return (f"Serveur « {host} » introuvable : vérifiez la connexion internet "
                "(ou l'orthographe du nom du serveur, s'il vient d'être saisi).")
    if isinstance(exc, (ConnectionRefusedError, TimeoutError, socket.timeout)):
        return (f"Aucune réponse de {host}:{port}. Vérifiez le port, ou un pare-feu / "
                "antivirus qui bloquerait la connexion.")
    if isinstance(exc, UnicodeEncodeError):
        return ("Le mot de passe ou l'identifiant contient un caractère accentué ou spécial "
                "que le protocole n'accepte pas. Essayez un mot de passe sans accents.")
    if isinstance(exc, smtplib.SMTPNotSupportedError):
        return "Le serveur ne propose pas STARTTLS sur ce port : essayez 465 en SSL."
    return f"{service} : {type(exc).__name__} – {exc}"


# --- Test de connexion -----------------------------------------------------------

@dataclass
class StepResult:
    label: str
    ok: bool
    detail: str = ""


@dataclass
class ConnectionReport:
    steps: list[StepResult] = field(default_factory=list)
    folders: list[Folder] = field(default_factory=list)
    sent_folder: str | None = None
    junk_folder: str | None = None

    @property
    def ok(self) -> bool:
        return bool(self.steps) and all(s.ok for s in self.steps)


def build_self_test_message(cfg: ServerConfig) -> EmailMessage:
    msg = EmailMessage()
    msg["From"] = formataddr((cfg.display_name, cfg.email))
    msg["To"] = cfg.email
    msg["Subject"] = "Test de connexion – ODDO Séquences"
    msg["Date"] = formatdate(localtime=False)
    msg["Message-ID"] = make_msgid(domain=cfg.domain)
    msg.set_content(
        "Ceci est un email de test envoyé par ODDO Séquences.\n"
        "S'il est arrivé dans votre boîte de réception, l'envoi SMTP fonctionne.\n"
    )
    return msg


def check_connection(cfg: ServerConfig, send_test_email: bool = True) -> ConnectionReport:
    report = ConnectionReport()

    # 1) SMTP : connexion + authentification (+ email de test)
    try:
        with open_smtp(cfg) as smtp:
            report.steps.append(StepResult(
                "SMTP", True, f"Connecté à {cfg.smtp_host}:{cfg.smtp_port} ({cfg.smtp_security.upper()})"))
            if send_test_email:
                smtp.send_message(build_self_test_message(cfg))
                report.steps.append(StepResult("Email de test", True, f"Envoyé à {cfg.email}"))
    except Exception as exc:  # noqa: BLE001 – on veut afficher toute erreur à l'utilisateur
        report.steps.append(StepResult("SMTP", False,
                                       explain_error(exc, "SMTP", cfg.smtp_host, cfg.smtp_port)))

    # 2) IMAP : connexion + liste des dossiers (indépendant du résultat SMTP)
    try:
        conn = open_imap(cfg)
        try:
            report.folders = list_folders(conn)
        finally:
            try:
                conn.logout()
            except Exception:  # noqa: BLE001
                pass
        report.sent_folder = detect_special(report.folders, "\\Sent", _SENT_GUESSES)
        report.junk_folder = detect_special(report.folders, "\\Junk", _JUNK_GUESSES)
        report.steps.append(StepResult(
            "IMAP", True,
            f"Connecté à {cfg.imap_host}:{cfg.imap_port}, {len(report.folders)} dossier(s) trouvé(s)"))
    except Exception as exc:  # noqa: BLE001
        report.steps.append(StepResult("IMAP", False,
                                       explain_error(exc, "IMAP", cfg.imap_host, cfg.imap_port)))
    return report

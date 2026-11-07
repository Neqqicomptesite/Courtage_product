"""Faux serveur SMTP (aiosmtpd) : reçoit les emails et les garde en mémoire."""
import socket
from dataclasses import dataclass, field

from aiosmtpd.controller import Controller
from aiosmtpd.smtp import AuthResult, LoginPassword

from tests.fakes.certs import server_context


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@dataclass
class Received:
    mail_from: str
    rcpt_tos: list[str]
    data: bytes


@dataclass
class _Handler:
    messages: list[Received] = field(default_factory=list)
    reject_rcpt: dict[str, str] = field(default_factory=dict)  # adresse -> réponse SMTP (ex. "550 ...")

    async def handle_RCPT(self, server, session, envelope, address, rcpt_options):
        if address.lower() in self.reject_rcpt:
            return self.reject_rcpt[address.lower()]
        envelope.rcpt_tos.append(address)
        return "250 OK"

    async def handle_DATA(self, server, session, envelope):
        self.messages.append(Received(envelope.mail_from, list(envelope.rcpt_tos), envelope.content))
        return "250 Message accepted"


class FakeSmtpServer:
    """mode="ssl" : TLS dès la connexion (port 465) ; mode="starttls" : TLS après STARTTLS (587)."""

    def __init__(self, username: str, password: str, mode: str = "ssl", port: int | None = None):
        self.username, self.password, self.mode = username, password, mode
        self.handler = _Handler()
        self.port = port or free_port()
        self.auth_failures = 0

        def authenticator(server, session, envelope, mechanism, auth_data):
            ok = (isinstance(auth_data, LoginPassword)
                  and auth_data.login.decode() == self.username
                  and auth_data.password.decode() == self.password)
            if not ok:
                self.auth_failures += 1
            # handled=False : laisse aiosmtpd répondre « 535 » au client. (Avec la valeur
            # par défaut handled=True, le serveur ne répond rien et le client attend.)
            return AuthResult(success=ok, handled=False)

        # AUTH LOGIN exclu : smtplib l'essaie après un refus PLAIN, et l'implémentation
        # d'aiosmtpd attend alors une réponse que smtplib n'envoie pas (blocage du test).
        kwargs = dict(hostname="127.0.0.1", port=self.port, authenticator=authenticator,
                      auth_exclude_mechanism=["LOGIN"])
        if mode == "ssl":
            kwargs.update(ssl_context=server_context(), auth_require_tls=False)
        else:
            kwargs.update(tls_context=server_context(), require_starttls=True)
        self.controller = Controller(self.handler, **kwargs)

    @property
    def messages(self) -> list[Received]:
        return self.handler.messages

    def start(self):
        self.controller.start()
        return self

    def stop(self):
        self.controller.stop()

"""Certificats TLS de TEST (autorité « ODDO Test CA », valable jusqu'en 2046).

La clé de l'autorité a été détruite après création : ces fichiers ne
permettent de signer aucun autre certificat. Ils ne servent qu'aux faux serveurs.
"""
import ssl
from pathlib import Path

CERT_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "certs"
CA_FILE = CERT_DIR / "ca.pem"
SERVER_CERT = CERT_DIR / "server.pem"
SERVER_KEY = CERT_DIR / "server.key"


def server_context() -> ssl.SSLContext:
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(SERVER_CERT, SERVER_KEY)
    return ctx

"""Protection d'une app locale sans mot de passe.

Écouter sur 127.0.0.1 empêche les autres PC de se connecter, mais PAS un site
web malveillant ouvert dans votre navigateur d'envoyer des requêtes vers
http://127.0.0.1:8765 (attaque « CSRF »), ni d'utiliser un faux nom de domaine
qui pointe vers 127.0.0.1 (« DNS rebinding »). D'où deux vérifications :

1. l'en-tête Host doit être 127.0.0.1:8765 ou localhost:8765 ;
2. pour toute requête qui modifie quelque chose (POST...), l'en-tête Origin
   (ou à défaut Referer) doit venir de l'app elle-même.

C'est aussi le point d'extension prévu pour ajouter une authentification plus tard (§10).
"""
from urllib.parse import urlsplit

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import PlainTextResponse

SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


class LocalOnlyMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, allowed_hosts: set[str]):
        super().__init__(app)
        self.allowed_hosts = {h.lower() for h in allowed_hosts}

    def _origin_ok(self, value: str | None) -> bool:
        if not value:
            return True  # absent : client non-navigateur (tests, curl). Les navigateurs l'envoient.
        netloc = urlsplit(value).netloc.lower()
        return netloc in self.allowed_hosts

    async def dispatch(self, request: Request, call_next):
        host = request.headers.get("host", "").lower()
        if host not in self.allowed_hosts:
            return PlainTextResponse("Hôte non autorisé.", status_code=400)
        if request.method not in SAFE_METHODS:
            origin = request.headers.get("origin")
            if origin is None:
                origin = request.headers.get("referer")
            if not self._origin_ok(origin):
                return PlainTextResponse("Requête refusée (origine externe).", status_code=403)
        return await call_next(request)

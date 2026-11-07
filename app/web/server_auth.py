"""V3 (serveur) : chaque appel à /api doit porter un jeton de connexion valide.

Middleware ASGI « pur » (pas BaseHTTPMiddleware) : l'employé est fixé dans le contexte
(app.current) pour toute la durée de la requête, y compris dans les fonctions exécutées
dans un autre thread.
"""
from __future__ import annotations

import json

import anyio

from starlette.types import ASGIApp, Receive, Scope, Send

from app import auth
from app.current import as_user

PUBLIC = ("/api/auth/config", "/api/health")


class SupabaseAuthMiddleware:
    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        path = scope.get("path", "")
        if scope["type"] != "http" or not path.startswith("/api/") or path.startswith(PUBLIC):
            await self.app(scope, receive, send)
            return
        headers = {k.decode().lower(): v.decode() for k, v in scope.get("headers", [])}
        token = headers.get("authorization", "")
        token = token[7:].strip() if token.lower().startswith("bearer ") else ""
        try:
            if not token:
                raise auth.AuthError("Connexion requise.")
            uid, role, _email = await anyio.to_thread.run_sync(lambda: auth.resolve_user(auth.verify_token(token)))
        except auth.AuthError as exc:
            body = json.dumps({"detail": str(exc), "auth": True}).encode()
            await send({"type": "http.response.start", "status": exc.status,
                        "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())]})
            await send({"type": "http.response.body", "body": body})
            return
        scope.setdefault("state", {})["user_id"] = uid
        with as_user(uid, role):
            await self.app(scope, receive, send)

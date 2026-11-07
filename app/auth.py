"""V3 : connexion des employés (comptes Supabase).

Le navigateur se connecte auprès de Supabase (email + mot de passe) et reçoit un jeton signé.
Il l'envoie à chaque appel (« Authorization: Bearer … »). Ici on vérifie la signature avec les
clés publiques du projet Supabase (JWKS), puis on retrouve l'employé dans `app_user`.
Seuls les employés invités par l'administrateur sont acceptés : un compte Supabase créé par
quelqu'un d'autre est refusé.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import timedelta
from functools import lru_cache

import jwt
from sqlalchemy import func, select

from app.db import get_session
from app.models import AppUser
from app.timeutil import utcnow


class AuthError(Exception):
    def __init__(self, message: str, status: int = 401):
        super().__init__(message)
        self.status = status


@dataclass(frozen=True)
class SupabaseConfig:
    url: str
    publishable_key: str
    secret_key: str
    jwt_secret: str  # ancien mode (HS256), facultatif

    @property
    def issuer(self) -> str:
        return f"{self.url}/auth/v1"


def config() -> SupabaseConfig:
    return SupabaseConfig(
        url=os.environ.get("SUPABASE_URL", "").rstrip("/"),
        publishable_key=os.environ.get("SUPABASE_PUBLISHABLE_KEY", ""),
        secret_key=os.environ.get("SUPABASE_SECRET_KEY", ""),
        jwt_secret=os.environ.get("SUPABASE_JWT_SECRET", ""),
    )


@lru_cache(maxsize=4)
def _jwks_client(url: str) -> jwt.PyJWKClient:
    return jwt.PyJWKClient(f"{url}/auth/v1/.well-known/jwks.json", cache_keys=True, lifespan=3600)


def verify_token(token: str, cfg: SupabaseConfig | None = None) -> dict:
    """Vérifie le jeton Supabase et renvoie ses informations (sub, email…)."""
    cfg = cfg or config()
    try:
        header = jwt.get_unverified_header(token)
        if header.get("alg") == "HS256":
            if not cfg.jwt_secret:
                raise AuthError("Jeton d'un type non accepté.")
            key: object = cfg.jwt_secret
        else:
            key = _jwks_client(cfg.url).get_signing_key_from_jwt(token).key
        return jwt.decode(token, key, algorithms=["ES256", "RS256", "HS256"],
                          audience="authenticated", issuer=cfg.issuer, leeway=30)
    except AuthError:
        raise
    except jwt.ExpiredSignatureError as exc:
        raise AuthError("Session expirée : reconnectez-vous.") from exc
    except Exception as exc:  # noqa: BLE001 – tout jeton douteux est refusé
        raise AuthError("Connexion invalide : reconnectez-vous.") from exc


def resolve_user(claims: dict) -> tuple[int, str, str]:
    """(id, rôle, email) de l'employé correspondant au jeton. Lie le compte Supabase à
    l'employé invité lors de sa première connexion (par l'adresse email)."""
    sub = str(claims.get("sub") or "")
    email = str(claims.get("email") or "").strip().lower()
    with get_session() as s, s.begin():
        u = s.scalars(select(AppUser).where(AppUser.auth_id == sub)).first() if sub else None
        if u is None and email:
            u = s.scalars(select(AppUser).where(func.lower(AppUser.email) == email)).first()
            if u is not None and u.auth_id and u.auth_id != sub:
                u = None  # adresse déjà liée à un autre compte Supabase
            elif u is not None:
                u.auth_id = sub
        if u is None:
            raise AuthError("Ce compte n'a pas accès à ODDO Séquences. Demandez une invitation.", 403)
        if not u.active:
            raise AuthError("Compte désactivé. Contactez l'administrateur.", 403)
        now = utcnow()
        if u.last_seen_at is None or now - u.last_seen_at > timedelta(minutes=5):
            u.last_seen_at = now
        return u.id, u.role, u.email


def ensure_admin_from_env() -> None:
    """Au démarrage du serveur : l'administrateur indiqué par ODDO_ADMIN_EMAIL existe."""
    email = os.environ.get("ODDO_ADMIN_EMAIL", "").strip().lower()
    if not email:
        return
    name = os.environ.get("ODDO_ADMIN_NAME", "").strip()
    with get_session() as s, s.begin():
        u = s.scalars(select(AppUser).where(func.lower(AppUser.email) == email)).first()
        if u is None:
            s.add(AppUser(email=email, full_name=name, role="admin"))
        elif u.role != "admin" or not u.active:
            u.role, u.active = "admin", True

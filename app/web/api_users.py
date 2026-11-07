"""V3 : comptes des employés (l'administrateur invite, désactive, change le rôle) et « moi »."""
from __future__ import annotations

import json
import urllib.request

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from app import auth
from app.current import is_admin, user_id
from app.db import get_session
from app.models import AppUser, Contact, Mailbox
from app.paths import is_server_mode

router = APIRouter(prefix="/api")


def _user_json(u: AppUser, mb: Mailbox | None = None, n_contacts: int = 0) -> dict:
    return {"id": u.id, "email": u.email, "full_name": u.full_name, "role": u.role, "active": u.active,
            "linked": bool(u.auth_id), "last_seen_at": u.last_seen_at.isoformat() if u.last_seen_at else None,
            "mailbox": mb.email if mb else None, "contacts": n_contacts}


@router.get("/auth/config")
def auth_config():
    """Ce dont le navigateur a besoin pour afficher l'écran de connexion (rien de secret)."""
    c = auth.config()
    return {"server_mode": is_server_mode(), "supabase_url": c.url, "publishable_key": c.publishable_key}


@router.get("/health")
def health():
    return {"ok": True}


@router.get("/me")
def me():
    uid = user_id()
    if uid is None:
        return {"id": None, "role": "admin", "server_mode": False}
    with get_session() as s:
        u = s.get(AppUser, uid)
        mb = s.scalars(select(Mailbox).where(Mailbox.user_id == uid)).first()
        return {**_user_json(u, mb), "server_mode": True}


def _require_admin() -> None:
    if not is_admin():
        raise HTTPException(403, "Réservé à l'administrateur.")


@router.get("/admin/users")
def list_users():
    _require_admin()
    with get_session() as s:
        boxes = {m.user_id: m for m in s.scalars(select(Mailbox).where(Mailbox.user_id.is_not(None)))}
        counts = dict(s.execute(select(Contact.owner_id, func.count(Contact.id)).group_by(Contact.owner_id)).all())
        return [_user_json(u, boxes.get(u.id), counts.get(u.id, 0))
                for u in s.scalars(select(AppUser).order_by(AppUser.full_name, AppUser.email))]


class InviteIn(BaseModel):
    email: str = Field(pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$", max_length=254)
    full_name: str = Field(default="", max_length=120)
    role: str = Field(default="user", pattern="^(admin|user)$")


def _supabase_invite(email: str) -> str | None:
    """Envoie l'email d'invitation Supabase (lien pour choisir son mot de passe).
    Renvoie un message d'erreur lisible, ou None si c'est parti."""
    c = auth.config()
    if not (c.url and c.secret_key):
        return "Supabase n'est pas configuré sur le serveur."
    import os
    from urllib.parse import quote
    url = f"{c.url}/auth/v1/invite"
    public = os.environ.get("ODDO_PUBLIC_URL", "").strip().rstrip("/")
    if public:  # le lien du mail ramène sur l'appli (sinon : « Site URL » réglée dans Supabase)
        url += "?redirect_to=" + quote(public + "/v2/", safe="")
    req = urllib.request.Request(url, data=json.dumps({"email": email}).encode(), method="POST",
                                 headers={"apikey": c.secret_key, "Authorization": f"Bearer {c.secret_key}",
                                          "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=15):
            return None
    except Exception as exc:  # noqa: BLE001
        detail = getattr(exc, "read", lambda: b"")().decode(errors="ignore")[:200]
        return f"Invitation non envoyée ({detail or exc})."


@router.post("/admin/users")
def invite_user(body: InviteIn):
    _require_admin()
    email = body.email.strip().lower()
    with get_session() as s, s.begin():
        if s.scalars(select(AppUser).where(func.lower(AppUser.email) == email)).first():
            raise HTTPException(409, "Cette personne a déjà un compte.")
        u = AppUser(email=email, full_name=body.full_name.strip(), role=body.role)
        s.add(u)
        s.flush()
        out = _user_json(u)
    err = _supabase_invite(email) if is_server_mode() else None
    return {**out, "invite_error": err}


class UserPatch(BaseModel):
    full_name: str | None = Field(default=None, max_length=120)
    role: str | None = Field(default=None, pattern="^(admin|user)$")
    active: bool | None = None


@router.patch("/admin/users/{uid}")
def update_user(uid: int, body: UserPatch):
    _require_admin()
    with get_session() as s, s.begin():
        u = s.get(AppUser, uid)
        if u is None:
            raise HTTPException(404, "Compte introuvable.")
        if uid == user_id() and (body.active is False or body.role == "user"):
            raise HTTPException(400, "Vous ne pouvez pas retirer vos propres droits d'administrateur.")
        for k in ("full_name", "role", "active"):
            v = getattr(body, k)
            if v is not None:
                setattr(u, k, v.strip() if isinstance(v, str) and k == "full_name" else v)
        return _user_json(u)


@router.post("/admin/users/{uid}/resend")
def resend_invite(uid: int):
    _require_admin()
    with get_session() as s:
        u = s.get(AppUser, uid)
        if u is None:
            raise HTTPException(404, "Compte introuvable.")
        email = u.email
    return {"invite_error": _supabase_invite(email)}

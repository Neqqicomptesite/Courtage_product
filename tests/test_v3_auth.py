"""V3 : connexion des employés (jetons Supabase), comptes, données propres à chacun."""
import time

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi.testclient import TestClient
from sqlalchemy import select

from app import auth
from app.current import as_user
from app.db import get_session
from app.models import AppUser, Mailbox, Secret

URL = "https://test.supabase.co"
KEY = ec.generate_private_key(ec.SECP256R1())


class _Jwks:
    def get_signing_key_from_jwt(self, token):
        return type("K", (), {"key": KEY.public_key()})()


def tok(email, sub=None, exp=3600, key=KEY):
    now = int(time.time())
    return jwt.encode({"sub": sub or f"uid-{email}", "email": email, "aud": "authenticated",
                       "iss": f"{URL}/auth/v1", "iat": now, "exp": now + exp}, key, algorithm="ES256")


def H(email, **kw):
    return {"Authorization": f"Bearer {tok(email, **kw)}", "Origin": "http://testserver"}


@pytest.fixture
def server(db, monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", URL)
    monkeypatch.setattr(auth, "_jwks_client", lambda url: _Jwks())
    from app.web import app as appmod
    monkeypatch.setattr(appmod, "is_server_mode", lambda: True)
    with get_session() as s, s.begin():
        s.add_all([AppUser(email="omar@oddo.ma", full_name="Omar", role="admin"),
                   AppUser(email="hamza@oddo.ma", full_name="Hamza", role="user"),
                   AppUser(email="parti@oddo.ma", full_name="Parti", role="user", active=False)])
    with TestClient(appmod.create_app(testing=True)) as c:
        yield c


def test_api_requires_login(server):
    assert server.get("/api/settings").status_code == 401
    r = server.get("/api/auth/config")
    assert r.status_code == 200 and "publishable_key" in r.json()


def test_invited_user_logs_in_and_is_linked(server):
    r = server.get("/api/me", headers=H("hamza@oddo.ma"))
    assert r.status_code == 200 and r.json()["email"] == "hamza@oddo.ma" and r.json()["role"] == "user"
    with get_session() as s:
        assert s.scalars(select(AppUser).where(AppUser.email == "hamza@oddo.ma")).one().auth_id == "uid-hamza@oddo.ma"


def test_refusals(server):
    assert server.get("/api/me", headers=H("inconnu@gmail.com")).status_code == 403
    assert server.get("/api/me", headers=H("parti@oddo.ma")).status_code == 403
    assert server.get("/api/me", headers=H("hamza@oddo.ma", exp=-120)).status_code == 401
    other = ec.generate_private_key(ec.SECP256R1())
    assert server.get("/api/me", headers=H("hamza@oddo.ma", key=other)).status_code == 401
    # adresse déjà liée à un autre compte Supabase : refusée
    server.get("/api/me", headers=H("hamza@oddo.ma"))
    assert server.get("/api/me", headers=H("hamza@oddo.ma", sub="autre")).status_code == 403


def test_admin_only_user_management(server):
    assert server.get("/api/admin/users", headers=H("hamza@oddo.ma")).status_code == 403
    r = server.post("/api/admin/users", json={"email": "Sara@oddo.ma", "full_name": "Sara"}, headers=H("omar@oddo.ma"))
    assert r.status_code == 200, r.text
    assert r.json()["email"] == "sara@oddo.ma"
    assert server.post("/api/admin/users", json={"email": "sara@oddo.ma"}, headers=H("omar@oddo.ma")).status_code == 409
    users = server.get("/api/admin/users", headers=H("omar@oddo.ma")).json()
    assert {u["email"] for u in users} >= {"omar@oddo.ma", "hamza@oddo.ma", "sara@oddo.ma"}
    hid = next(u["id"] for u in users if u["email"] == "hamza@oddo.ma")
    assert server.patch(f"/api/admin/users/{hid}", json={"active": False}, headers=H("omar@oddo.ma")).status_code == 200
    assert server.get("/api/me", headers=H("hamza@oddo.ma")).status_code == 403
    oid = next(u["id"] for u in users if u["email"] == "omar@oddo.ma")
    assert server.patch(f"/api/admin/users/{oid}", json={"role": "user"}, headers=H("omar@oddo.ma")).status_code == 400


def test_settings_and_mailbox_are_per_user(server):
    assert server.put("/api/settings/test-mode", json={"enabled": False}, headers=H("omar@oddo.ma")).status_code == 200
    assert server.get("/api/settings", headers=H("omar@oddo.ma")).json()["test_mode"] is False
    assert server.get("/api/settings", headers=H("hamza@oddo.ma")).json()["test_mode"] is True
    with get_session() as s, s.begin():
        oid = s.scalars(select(AppUser.id).where(AppUser.email == "omar@oddo.ma")).one()
        s.add(Mailbox(display_name="Omar", email="omar@oddo.ma", user_id=oid))
    assert server.get("/api/settings", headers=H("omar@oddo.ma")).json()["mailbox_exists"] is True
    assert server.get("/api/settings", headers=H("hamza@oddo.ma")).json()["mailbox_exists"] is False


def test_server_password_vault_encrypts(db, monkeypatch):
    from cryptography.fernet import Fernet
    from app import credentials, paths
    monkeypatch.setattr(paths, "is_server_mode", lambda: True)
    monkeypatch.setenv("ODDO_SECRET_KEY", Fernet.generate_key().decode())
    credentials.set_password("Omar@oddo.ma", "motdepasse-très-secret")
    assert credentials.get_password("omar@oddo.ma") == "motdepasse-très-secret"
    with get_session() as s:
        row = s.scalars(select(Secret)).one()
        assert "secret" not in row.value and row.account == "omar@oddo.ma"
    credentials.delete_password("omar@oddo.ma")
    assert credentials.get_password("omar@oddo.ma") is None
    monkeypatch.delenv("ODDO_SECRET_KEY")
    with pytest.raises(credentials.CredentialError):
        credentials.get_password("x@y.ma")


def test_as_user_scopes_settings_keys(db):
    from app import settings_store
    with get_session() as s, s.begin():
        with as_user(7):
            settings_store.set_(s, "followup_days", 5)
            settings_store.set_(s, "holidays", [])
    with get_session() as s:
        assert settings_store.get(s, "followup_days") == 3  # poste unique : inchangé
        with as_user(7):
            assert settings_store.get(s, "followup_days") == 5
        assert settings_store.get(s, "holidays") == []  # réglage commun


def _two_boxes():
    with get_session() as s, s.begin():
        ids = dict(s.execute(select(AppUser.email, AppUser.id)).all())
        s.add_all([Mailbox(display_name="Omar", email="omar@oddo.ma", user_id=ids["omar@oddo.ma"]),
                   Mailbox(display_name="Hamza", email="hamza@oddo.ma", user_id=ids["hamza@oddo.ma"])])
    return ids


def test_one_owner_per_prospect_and_private_campaigns(server):
    from tests.test_v223 import _setup
    from app.models import Contact
    ids = _two_boxes()
    g, p, seq = _setup()
    r = server.post(f"/api/sequences/{seq['P2']}/send", json={"contact_ids": [p]}, headers=H("omar@oddo.ma")).json()
    assert len(r["sent"]) == 1, r
    with get_session() as s:
        assert s.get(Contact, p).owner_id == ids["omar@oddo.ma"]
    r = server.post(f"/api/sequences/{seq['P2']}/send", json={"contact_ids": [p]}, headers=H("hamza@oddo.ma")).json()
    assert not r["sent"] and "suivi par Omar" in r["refused"][0]["reason"]
    # un assureur reste à tout le monde
    ov = {"1": {"subject": "Demande d'avenant – police 40.1 – Client A", "body": "Bonjour Karima,\n\nMerci.\n"}}
    for who in ("omar@oddo.ma", "hamza@oddo.ma"):
        r = server.post(f"/api/sequences/{seq['G1']}/send", json={"contact_ids": [g], "overrides": ov}, headers=H(who)).json()
        assert len(r["sent"]) == 1, (who, r)
    # chacun ne voit que ses campagnes
    omar = {c["id"] for c in server.get("/api/campaigns", headers=H("omar@oddo.ma")).json()}
    hamza = {c["id"] for c in server.get("/api/campaigns", headers=H("hamza@oddo.ma")).json()}
    assert omar and hamza and not (omar & hamza)
    assert server.get(f"/api/campaigns/{min(omar)}", headers=H("hamza@oddo.ma")).status_code == 404


def test_reminders_and_personal_templates_are_private(server):
    _two_boxes()
    r = server.post("/api/reminders", json={"title": "Appeler Atlas", "kind": "call", "due_on": "2030-01-10"},
                    headers=H("omar@oddo.ma"))
    assert r.status_code == 200, r.text
    agenda = lambda who: server.get("/api/reminders?start=2030-01-01&end=2030-01-31", headers=H(who)).json()
    assert "Appeler Atlas" in str(agenda("omar@oddo.ma")) and "Appeler Atlas" not in str(agenda("hamza@oddo.ma"))
    r = server.post("/api/sequences", json={"name": "Cotation AT", "category": "souscription", "steps": 1},
                    headers=H("hamza@oddo.ma"))
    assert r.status_code == 200, r.text
    names = lambda who: {q["name"] for q in server.get("/api/sequences", headers=H(who)).json()["items"]}
    assert "Cotation AT" in names("hamza@oddo.ma") and "Cotation AT" not in names("omar@oddo.ma")


def test_classic_pages_not_served_on_server(server):
    """Les pages V1 ne vérifient pas la connexion : absentes du serveur."""
    for path in ("/contacts/export", "/export", "/replies", "/settings/mailbox", "/sequences/1"):
        assert server.get(path, headers={"Origin": "http://testserver"}).status_code == 404, path
    assert server.get("/classique", follow_redirects=False).status_code in (302, 307)


def test_cookie_token_only_for_reading(server):
    """Le jeton en cookie (liens d'export, pièces jointes) marche en GET, jamais en écriture."""
    cookie = {"Cookie": f"oddo_at={tok('omar@oddo.ma')}", "Origin": "http://testserver"}
    assert server.get("/api/me", headers=cookie).status_code == 200
    assert server.post("/api/admin/users", json={"email": "x@oddo.ma"}, headers=cookie).status_code == 401


def test_export_via_api(server):
    r = server.get("/api/export", headers=H("omar@oddo.ma"))
    assert r.status_code == 200 and r.headers["content-type"].startswith("application/vnd.openxml")
    assert server.get("/api/export").status_code == 401


def test_invite_link_returns_to_app(server, monkeypatch):
    from app.web import api_users
    seen = {}

    class R:
        def __enter__(self): return self
        def __exit__(self, *a): return False

    def fake_urlopen(req, timeout=0):
        seen["url"] = req.full_url
        return R()
    monkeypatch.setenv("SUPABASE_SECRET_KEY", "sb_secret_test")
    monkeypatch.setenv("ODDO_PUBLIC_URL", "https://sequences.example.ma/")
    monkeypatch.setattr(api_users.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(api_users, "is_server_mode", lambda: True)
    r = server.post("/api/admin/users", json={"email": "new@oddo.ma", "full_name": "New"}, headers=H("omar@oddo.ma"))
    assert r.status_code == 200 and r.json()["invite_error"] is None
    assert seen["url"].endswith("/auth/v1/invite?redirect_to=https%3A%2F%2Fsequences.example.ma%2Fv2%2F")

"""V3 : cloisonnement entre employés, vérifié sur TOUTES les adresses de l'API.

Omar a une boîte, une campagne, des emails, un rappel, un modèle personnel et des événements
au journal, tous marqués « SECRET-OMAR ». On appelle ensuite chaque adresse GET de l'API en
tant que Hamza (avec les identifiants d'Omar quand l'adresse en demande) : aucune réponse ne
doit contenir ce marqueur. Puis on vérifie que Hamza ne peut rien modifier chez Omar.
"""
import re
from datetime import date

import pytest

from app.current import as_user
from app.db import get_session
from app.models import AppUser, Campaign, Contact, Enrollment, EventLog, Mailbox, Message, Reminder, Sequence, Step, StepVariant
from app.timeutil import utcnow
from app.web import (api, api_campaigns, api_companies, api_contacts, api_mailbox, api_misc, api_sequences, api_users, api_v3,
                     api_v28)
from tests.test_v3_auth import H, server  # noqa: F401  (fixture)

MARK = "SECRET-OMAR"


@pytest.fixture
def omar_data(server):  # noqa: F811
    with get_session() as s, s.begin():
        omar = s.query(AppUser).filter_by(email="omar@oddo.ma").one()
        hamza = s.query(AppUser).filter_by(email="hamza@oddo.ma").one()
        mb_o = Mailbox(display_name="Omar", email="omar@oddo.ma", user_id=omar.id)
        mb_h = Mailbox(display_name="Hamza", email="hamza@oddo.ma", user_id=hamza.id)
        seq = Sequence(name=f"Modèle {MARK}", owner_id=omar.id)
        prospect = Contact(email="prospect@client.ma", kind="prospect", owner_id=omar.id)
        s.add_all([mb_o, mb_h, seq, prospect])
        s.flush()
        st = Step(sequence_id=seq.id, position=1, body_template=f"Corps {MARK}")
        s.add(st)
        s.flush()
        s.add(StepVariant(step_id=st.id, label="A", subject_template=f"Objet {MARK}"))
        camp = Campaign(name=f"Campagne {MARK}", mailbox_id=mb_o.id, sequence_id=seq.id, status="active")
        s.add(camp)
        s.flush()
        enr = Enrollment(campaign_id=camp.id, contact_id=prospect.id, status="scheduled")
        s.add(enr)
        s.flush()
        out = Message(enrollment_id=enr.id, contact_id=prospect.id, mailbox_id=mb_o.id, direction="out",
                      subject=f"Envoi {MARK}", body_text=f"Texte {MARK}", sent_at=utcnow(), message_id="<o1@oddo.ma>")
        rep = Message(enrollment_id=enr.id, contact_id=prospect.id, mailbox_id=mb_o.id, direction="in",
                      subject=f"Re: Envoi {MARK}", body_text=f"Réponse {MARK}", received_at=utcnow(), kind="reply",
                      message_id="<r1@client.ma>")
        s.add_all([out, rep])
        s.add(Reminder(title=f"Rappel {MARK}", due_on=date.today(), user_id=omar.id, contact_id=prospect.id))
        s.add(EventLog(level="info", entity="campaign", entity_id=camp.id, text=f"Événement {MARK}", user_id=omar.id))
        s.flush()
        ids = {"camp": camp.id, "enr": enr.id, "msg": rep.id, "seq": seq.id, "step": st.id, "contact": prospect.id,
               "omar": omar.id, "hamza": hamza.id}
        s.add(Reminder(title="Rappel Hamza", due_on=date.today(), user_id=hamza.id))
    from app import scope
    scope.forget_cache()
    return ids


def _routes(method: str):
    for mod in (api, api_campaigns, api_companies, api_contacts, api_mailbox, api_misc, api_sequences, api_users, api_v3, api_v28):
        for r in mod.router.routes:
            if method in r.methods:
                yield r.path


# Adresses communes à l'équipe par conception (contacts, entreprises) : le contact d'Omar est
# visible, mais rien de SES échanges (emails, campagnes, rappels) ne doit y figurer.
PARAM_FOR = {"camp_id": "camp", "cid": None, "eid": "enr", "mid": "msg", "message_id": "msg", "rid": None,
             "sid": "seq", "step_id": "step", "uid": "omar", "aid": None, "bid": None, "token": None, "index": None}


def test_no_leak_on_any_get(server, omar_data):  # noqa: F811
    # contrôle : Omar voit bien ses données (sinon le test ne prouverait rien)
    assert MARK in server.get("/api/campaigns", headers=H("omar@oddo.ma")).text
    assert MARK in server.get(f"/api/contacts/{omar_data['contact']}", headers=H("omar@oddo.ma")).text
    checked, leaks = 0, []
    for path in _routes("GET"):
        if path in ("/api/auth/config", "/api/health", "/api/export"):
            continue
        params = re.findall(r"\{(\w+)(?::\w+)?\}", path)
        urls = []
        if not params:
            urls = [path]
        else:
            # contacts/{cid} et campaigns/{cid} : le même nom désigne des objets différents
            subst = dict(PARAM_FOR)
            if path.startswith("/api/campaigns/"):
                subst["cid"] = "camp"
            elif path.startswith("/api/contacts/"):
                subst["cid"] = "contact"
            if any(subst.get(p) is None for p in params):
                continue
            u = path
            for p in params:
                u = re.sub(r"\{" + p + r"(?::\w+)?\}", str(omar_data[subst[p]]), u)
            urls = [u]
        for u in urls:
            r = server.get(u, headers=H("hamza@oddo.ma"))
            checked += 1
            if MARK in r.text:
                leaks.append(f"{u} -> {r.status_code}")
    assert checked > 30
    assert not leaks, "Fuites : " + ", ".join(leaks)


def test_export_has_only_my_campaigns(server, omar_data):  # noqa: F811
    import io

    import openpyxl
    wb = openpyxl.load_workbook(io.BytesIO(server.get("/api/export", headers=H("hamza@oddo.ma")).content))
    text = " ".join(str(c.value) for ws in wb for row in ws.iter_rows() for c in row if c.value is not None)
    assert MARK not in text


def test_cannot_act_on_colleague_data(server, omar_data):  # noqa: F811
    h = H("hamza@oddo.ma")
    i = omar_data
    attempts = [
        ("post", f"/api/campaigns/{i['camp']}/pause", None),
        ("post", f"/api/enrollments/{i['enr']}/skip", None),
        ("post", f"/api/enrollments/{i['enr']}/send-now", None),
        ("post", f"/api/enrollments/{i['enr']}/retry", None),
        ("post", f"/api/enrollments/{i['enr']}/confirm-sent", None),
        ("post", f"/api/contacts/{i['contact']}/enrollments/{i['enr']}/remove", None),
        ("post", f"/api/replies/{i['msg']}/classify", {"classification": "not_interested"}),
        ("put", f"/api/replies/{i['msg']}/note", {"note": "x"}),
        ("post", f"/api/replies/{i['msg']}/dismiss", None),
        ("put", f"/api/sequences/{i['seq']}", {"name": "pirate"}),
        ("delete", f"/api/sequences/{i['seq']}", None),
    ]
    for method, url, body in attempts:
        r = getattr(server, method)(url, json=body, headers=h) if body is not None else getattr(server, method)(url, headers=h)
        refused = r.status_code in (400, 403, 404, 409, 422) or (r.status_code == 200 and r.json().get("ok") is False)
        assert refused, f"{method.upper()} {url} -> {r.status_code} {r.text[:120]}"
    with get_session() as s:
        camp = s.get(Campaign, i["camp"])
        assert camp.status == "active"
        assert s.get(Enrollment, i["enr"]).status == "scheduled"
        assert s.get(Message, i["msg"]).classification is None and not s.get(Message, i["msg"]).note
        assert s.get(Sequence, i["seq"]).name.endswith(MARK)
    with as_user(i["hamza"], "user"), get_session() as s:
        assert s.query(Reminder).count() == 1  # le sien seulement


def test_server_maintenance_endpoints_closed(server, monkeypatch):  # noqa: F811
    """Mise à jour par zip et sauvegardes SQLite : propres au PC ; sur le serveur elles
    permettraient d'installer du code ou d'écrire des fichiers. Fermées."""
    from app import paths
    monkeypatch.setattr(paths, "is_server_mode", lambda: True)
    h = H("omar@oddo.ma")
    for method, url, body in [("post", "/api/update/url", {"url": "https://pirate.example/x.zip"}),
                              ("post", "/api/update/install", None), ("post", "/api/update/check", None),
                              ("post", "/api/backups/copy-dir", {"path": "/etc"}), ("post", "/api/backups/now", None)]:
        r = getattr(server, method)(url, json=body, headers=h) if body else getattr(server, method)(url, headers=h)
        assert r.status_code == 404, f"{url} -> {r.status_code}"


def test_shared_data_protected_from_employees(server, omar_data):  # noqa: F811
    """Modèles communs, entreprises, exclusions : modifiables par l'administrateur seulement ;
    un employé duplique un modèle commun pour avoir sa version."""
    h, o = H("hamza@oddo.ma"), H("omar@oddo.ma")
    with get_session() as s, s.begin():
        shared = Sequence(name="Modèle commun")
        s.add(shared)
        s.flush()
        s.add(Step(sequence_id=shared.id, position=1, body_template="Bonjour"))
        sid = shared.id
    r = server.get(f"/api/sequences/{sid}", headers=h)
    assert r.json()["shared"] is True and r.json()["editable"] is False
    assert server.put(f"/api/sequences/{sid}", json={"name": "x", "steps": []}, headers=h).status_code == 403
    assert server.delete(f"/api/sequences/{sid}", headers=h).status_code == 403
    assert server.post(f"/api/sequences/{sid}/steps", headers=h).status_code == 403
    dup = server.post(f"/api/sequences/{sid}/duplicate", headers=h)
    assert dup.status_code == 200
    mine = server.get(f"/api/sequences/{dup.json()['id']}", headers=h).json()
    assert mine["editable"] is True and mine["shared"] is False
    assert server.post(f"/api/sequences/{mine['id']}/steps", headers=h).status_code == 200
    assert server.get(f"/api/sequences/{mine['id']}", headers=o).status_code == 404   # modèle perso : invisible pour Omar
    assert server.get(f"/api/sequences/{sid}", headers=o).json()["editable"] is True  # admin
    # contact suivi par Omar : Hamza ne peut ni l'effacer ni le réactiver
    r = server.post(f"/api/contacts/{omar_data['contact']}/erase", json={"confirm": "EFFACER"}, headers=h)
    assert r.status_code == 403
    with get_session() as s:
        assert s.get(Contact, omar_data["contact"]) is not None
    from app.models import Company
    with get_session() as s, s.begin():
        comp = Company(name="Société test", name_key="societe test")
        s.add(comp)
        s.flush()
        comp_id = comp.id
    assert server.delete(f"/api/companies/{comp_id}", headers=h).status_code == 403
    assert server.delete(f"/api/companies/{comp_id}", headers=o).status_code == 200


def test_indicators_many_matches_single(server, omar_data):  # noqa: F811
    """La version groupée (V3) donne exactement les mêmes chiffres que l'ancienne, campagne par campagne."""
    from app import stats
    with as_user(omar_data["omar"], "admin"), get_session() as s:
        ids = [c.id for c in s.query(Campaign).all()]
        many = stats.indicators_many(s, ids)
        for cid in ids:
            one = stats.indicators(s, cid)
            assert vars(one) == vars(many[cid])
        assert many[omar_data["camp"]].sent_total == 1 and many[omar_data["camp"]].replies == 1


def test_long_text_is_cut_to_column_size(db):
    """PostgreSQL refuse un texte trop long pour sa colonne : coupé au lieu de faire échouer l'import."""
    with get_session() as s, s.begin():
        s.add(Contact(email="long@test.ma", first_name="A" * 300, job_title="P" * 600))
    with get_session() as s:
        c = s.query(Contact).filter_by(email="long@test.ma").one()
        assert len(c.first_name) == 120 and len(c.job_title) == 255


def test_mailbox_cache_is_per_employee(monkeypatch):
    """Revue externe, point 1 : le cache de la boîte mail (liste et emails ouverts) était commun.
    Les UID IMAP étant propres à chaque boîte, l'email n°42 de A s'affichait pour l'email n°42 de B."""
    from app import mailbox_browser as mbx

    boxes = {1: b"Subject: Sinistre confidentiel du client de A\r\n\r\nA", 2: b"Subject: Email de B\r\n\r\nB"}

    class Conn:
        def __init__(self, raw):
            self.raw = raw

        def uid(self, *a):
            return "OK", [(b"42 (BODY[] {10}", self.raw)]

    monkeypatch.setattr(mbx, "_context", lambda: object())
    monkeypatch.setattr(mbx, "_select_readonly", lambda conn, folder: None)
    monkeypatch.setattr(mbx, "_close", lambda conn: None)
    from app.current import user_id
    monkeypatch.setattr(mbx, "_open", lambda ctx, f=None: Conn(boxes[user_id()]))
    mbx._raw_cache.clear()
    with as_user(1, "admin"):
        assert b"client de A" in mbx._fetch_raw("INBOX", 42)
    with as_user(2, "user"):
        assert mbx._fetch_raw("INBOX", 42) == boxes[2]
        mbx.invalidate("INBOX")   # n'efface que le cache de B
    assert any(k[0] == 1 for k in mbx._raw_cache) and not any(k[0] == 2 for k in mbx._raw_cache)
    mbx._raw_cache.clear()


def test_supabase_api_roles_locked_out(db):
    """Revue externe, point 2 : sur Supabase, les rôles de l'API publique (anon, authenticated)
    recevaient par défaut tous les droits sur les tables créées en SQL. Elles doivent être
    fermées (RLS sans règle + droits retirés), le propriétaire (le serveur) gardant l'accès."""
    from sqlalchemy import text
    if db.dialect.name != "postgresql":
        pytest.skip("propre à PostgreSQL")
    from app.db_lockdown import lock_down
    with db.begin() as c:
        c.execute(text("DO $$BEGIN IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='anon') THEN CREATE ROLE anon NOLOGIN; END IF;"
                       " IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='authenticated') THEN CREATE ROLE authenticated NOLOGIN; END IF; END$$"))
        c.execute(text("GRANT USAGE ON SCHEMA public TO anon, authenticated"))
        c.execute(text("GRANT ALL ON ALL TABLES IN SCHEMA public TO anon, authenticated"))  # comme Supabase
        lock_down(c)
    with db.connect() as c:
        assert c.scalar(text("SELECT count(*) FROM pg_tables WHERE schemaname='public' AND NOT rowsecurity")) == 0
        assert c.scalar(text("SELECT count(*) FROM information_schema.role_table_grants "
                             "WHERE grantee IN ('anon','authenticated') AND table_schema='public'")) == 0
        c.execute(text("SET ROLE anon"))
        with pytest.raises(Exception):
            c.execute(text("SELECT count(*) FROM contact"))


def test_cannot_take_colleague_mailbox_or_password(server, omar_data):  # noqa: F811
    """Revue externe, point 5 : saisir l'adresse d'un collègue dans ses réglages ne doit ni
    réussir, ni remplacer son mot de passe (rangé sous cette adresse)."""
    from app import credentials
    credentials.set_password("omar@oddo.ma", "mot-de-passe-omar")
    body = {"display_name": "Hamza", "email": "omar@oddo.ma", "smtp_host": "smtp.test.ma", "smtp_port": 587,
            "smtp_security": "starttls", "imap_host": "imap.test.ma", "imap_port": 993, "username": "omar@oddo.ma",
            "password": "pirate", "signature": "", "watched_folders": ["INBOX"]}
    r = server.put("/api/settings/mailbox", json=body, headers=H("hamza@oddo.ma"))
    assert r.status_code in (400, 409, 422), r.text
    assert credentials.get_password("omar@oddo.ma") == "mot-de-passe-omar"


def test_only_web_links_are_kept():
    """Revue externe, point 6 : un lien « javascript:… » importé deviendrait cliquable par tous."""
    from app.models import safe_web_url
    assert safe_web_url("javascript:alert(1)") is None
    assert safe_web_url(" JavaScript:alert(1)") is None
    assert safe_web_url("data:text/html,x") is None
    assert safe_web_url("//evil.example") is None
    assert safe_web_url("exemple.ma") == "https://exemple.ma"
    assert safe_web_url("https://www.linkedin.com/in/x") == "https://www.linkedin.com/in/x"
    assert Contact(email="a@b.ma", linkedin_url="javascript:alert(1)").linkedin_url is None


def test_no_user_is_not_admin_on_server(monkeypatch):
    """Revue externe : sans employé en cours, refus par défaut sur le serveur (vrai seulement sur le PC)."""
    from app import current, paths
    monkeypatch.setattr(paths, "is_server_mode", lambda: True)
    assert current.is_admin() is False
    monkeypatch.setattr(paths, "is_server_mode", lambda: False)
    assert current.is_admin() is True


def test_mail_server_guard_on_server(monkeypatch):
    """Revue externe : « Tester la connexion » ne doit pas viser le serveur lui-même ni un port quelconque."""
    from app import paths
    from app.web import routes_settings
    monkeypatch.setattr(paths, "is_server_mode", lambda: True)
    errors = {}
    routes_settings._server_guard({"smtp_host": "127.0.0.1", "smtp_port": 587, "imap_host": "localhost", "imap_port": 6379}, errors)
    assert "smtp_host" in errors and "imap_port" in errors


def test_interface_security_headers(server):  # noqa: F811
    from app.paths import STATIC_DIR
    if not (STATIC_DIR / "v2" / "index.html").exists():
        pytest.skip("interface non compilée")
    r = server.get("/v2/", headers={"Origin": "http://testserver"})
    csp = r.headers["content-security-policy"]
    assert "script-src 'self' 'sha256-" in csp and "frame-ancestors 'none'" in csp and "test.supabase.co" in csp
    assert r.headers["x-frame-options"] == "DENY" and r.headers["x-content-type-options"] == "nosniff"


def test_new_colleague_mailbox_form_is_prefilled(server):  # noqa: F811
    """Un collègue arrive : formulaire de boîte pré-rempli avec SES nom et email et les serveurs de
    l'admin (587/STARTTLS qui passent depuis le serveur), jamais un mot de passe."""
    with get_session() as s, s.begin():
        omar = s.query(AppUser).filter_by(email="omar@oddo.ma").one()
        s.add(Mailbox(display_name="Omar", email="omar@oddo.ma", user_id=omar.id, smtp_host="mail.oddo.ma",
                      smtp_port=587, smtp_security="starttls", imap_host="mail.oddo.ma", imap_port=993,
                      username="omar@oddo.ma", sent_folder="INBOX.Sent"))
    from app import scope
    scope.forget_cache()
    d = server.get("/api/settings", headers=H("hamza@oddo.ma")).json()
    mb = d["mailbox"]
    assert d["mailbox_exists"] is False and d["has_password"] is False
    assert mb["email"] == "hamza@oddo.ma" and mb["username"] == "hamza@oddo.ma"
    assert (mb["smtp_host"], mb["smtp_port"], mb["smtp_security"]) == ("mail.oddo.ma", 587, "starttls")
    assert mb["sent_folder"] == "INBOX.Sent"

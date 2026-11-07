"""M1 : page Réglages, mot de passe dans keyring, test de connexion via l'interface, sécurité locale."""
from app import credentials
from app.db import get_session
from app.mailbox_service import get_primary
from app.paths import db_path
from tests.conftest import PASSWORD, USER

ORIGIN = {"Origin": "http://testserver"}


def _mailbox_form(smtp_port=465, imap_port=993, password=PASSWORD, **over):
    data = {
        "display_name": "Omar Douiri", "email": USER,
        "smtp_host": "127.0.0.1", "smtp_port": str(smtp_port), "smtp_security": "ssl",
        "imap_host": "127.0.0.1", "imap_port": str(imap_port),
        "username": USER, "password": password,
        "signature": "Omar Douiri\nODDO Assurance",
    }
    data.update(over)
    return data


def test_settings_page_renders_in_french_with_test_banner(client):
    r = client.get("/settings")
    assert r.status_code == 200
    assert "Mode test activé" in r.text
    assert "Tester la connexion" in r.text
    assert "Gestionnaire d'identification Windows" in r.text
    assert "2026-11-06 Marche Verte" in r.text


def test_dashboard_and_help_pages(client):
    assert "Première étape" in client.get("/classique").text
    assert "DKIM" in client.get("/aide/delivrabilite").text


def test_save_mailbox_stores_password_only_in_keyring(client, memory_keyring):
    r = client.post("/settings/mailbox", data=_mailbox_form(), headers=ORIGIN, follow_redirects=False)
    assert r.status_code == 303
    assert credentials.get_password(USER) == PASSWORD
    with get_session() as s:
        mb = get_primary(s)
        assert mb.smtp_host == "127.0.0.1" and mb.signature.endswith("ODDO Assurance")
    # Le mot de passe ne doit apparaître nulle part dans les fichiers de la base.
    for f in db_path().parent.glob("oddo.db*"):
        assert PASSWORD.encode() not in f.read_bytes()


def test_blank_password_keeps_existing_one(client):
    client.post("/settings/mailbox", data=_mailbox_form(), headers=ORIGIN)
    r = client.post("/settings/mailbox", data=_mailbox_form(password="", smtp_host="smtp.autre.ma"),
                    headers=ORIGIN, follow_redirects=False)
    assert r.status_code == 303
    assert credentials.get_password(USER) == PASSWORD
    assert "enregistré" in client.get("/settings").text


def test_first_save_requires_password(client):
    r = client.post("/settings/mailbox", data=_mailbox_form(password=""), headers=ORIGIN)
    assert r.status_code == 422
    assert "Le mot de passe est obligatoire" in r.text


def test_mailbox_validation_errors(client):
    r = client.post("/settings/mailbox", data=_mailbox_form(email="pas-un-email", smtp_port="abc"),
                    headers=ORIGIN)
    assert r.status_code == 422
    assert "pas une adresse email valide" in r.text
    assert "nombre entier" in r.text


def test_connection_button_lists_folders(client, smtp_ssl, imap_server):
    r = client.post("/settings/test-connection",
                    data=_mailbox_form(smtp_port=smtp_ssl.port, imap_port=imap_server.port),
                    headers=ORIGIN)
    assert r.status_code == 200
    assert "Connexion réussie" in r.text
    assert "INBOX.Sent" in r.text and "Envoyés détecté" in r.text
    # Bloc « hors bande » qui met à jour les choix de dossiers dans le formulaire
    assert 'hx-swap-oob="true"' in r.text
    assert '<option value="INBOX.Sent" selected>' in r.text
    assert len(smtp_ssl.messages) == 1  # email de test à soi-même
    # La liste des dossiers est mémorisée pour les prochaines visites
    assert "INBOX.Junk" in client.get("/settings").text


def test_connection_uses_stored_password_when_field_blank(client, smtp_ssl, imap_server):
    client.post("/settings/mailbox", data=_mailbox_form(), headers=ORIGIN)
    r = client.post("/settings/test-connection",
                    data=_mailbox_form(smtp_port=smtp_ssl.port, imap_port=imap_server.port,
                                       password="", send_test_email="off"),
                    headers=ORIGIN)
    assert "Connexion réussie" in r.text
    assert smtp_ssl.messages == []  # case décochée : pas d'email de test


def test_sending_settings_require_mailbox_then_validate(client):
    form = {"send_days": ["0", "1", "2", "3", "4"], "w1_start": "09:00", "w1_end": "12:30",
            "w2_start": "14:30", "w2_end": "17:30", "holidays": "2026-11-06 Marche Verte",
            "daily_cap": "25", "hourly_cap": "10", "min_gap_s": "90", "max_gap_s": "240",
            "rampup_per_day": "10", "unsubscribe_line": "Répondez STOP.", "digest_time": "18:00",
            "digest_recipient": ""}
    r = client.post("/settings/sending", data=form, headers=ORIGIN)
    assert r.status_code == 422 and "Enregistrez d'abord la boîte mail" in r.text

    client.post("/settings/mailbox", data=_mailbox_form(), headers=ORIGIN)
    bad = dict(form, min_gap_s="300", max_gap_s="100", w2_start="12:00", holidays="06/11/2026 Marche")
    r = client.post("/settings/sending", data=bad, headers=ORIGIN)
    assert r.status_code == 422
    assert "supérieur ou égal au délai minimum" in r.text
    assert "La plage 2 doit commencer après" in r.text
    assert "AAAA-MM-JJ" in r.text

    r = client.post("/settings/sending", data=dict(form, daily_cap="60"), headers=ORIGIN,
                    follow_redirects=False)
    assert r.status_code == 303
    page = client.get("/settings").text
    assert "Au-delà de 50 emails par jour" in page  # avertissement §4


def test_unsubscribe_line_cannot_be_removed(client):
    client.post("/settings/mailbox", data=_mailbox_form(), headers=ORIGIN)
    form = {"send_days": ["0"], "w1_start": "09:00", "w1_end": "12:00", "holidays": "",
            "daily_cap": "25", "hourly_cap": "10", "min_gap_s": "90", "max_gap_s": "240",
            "rampup_per_day": "10", "unsubscribe_line": "   ", "digest_time": "18:00"}
    r = client.post("/settings/sending", data=form, headers=ORIGIN)
    assert r.status_code == 422 and "désinscription est obligatoire" in r.text


def test_toggle_test_mode_changes_banner(client):
    r = client.post("/settings/test-mode", data={"enabled": "0"}, headers=ORIGIN)
    assert "les emails partent réellement" in r.text
    r = client.post("/settings/test-mode", data={"enabled": "1"}, headers=ORIGIN)
    assert "Mode test activé" in r.text


def test_cross_site_post_is_refused(client):
    r = client.post("/settings/test-mode", data={"enabled": "0"},
                    headers={"Origin": "https://site-malveillant.example"})
    assert r.status_code == 403
    assert "Mode test activé" in client.get("/settings").text  # rien n'a changé


def test_foreign_host_header_is_refused(client):
    r = client.get("/settings", headers={"Host": "attaquant.example:8765"})
    assert r.status_code == 400

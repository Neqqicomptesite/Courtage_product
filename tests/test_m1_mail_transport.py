"""M1 : test de connexion SMTP/IMAP contre les faux serveurs."""
from email import message_from_bytes

from app.mail import imap_utf7
from app.mail.transport import (
    Folder, ServerConfig, check_connection, detect_special, parse_list_response,
)
from tests.conftest import PASSWORD, USER


def _cfg(smtp, imap, mode="ssl", password=PASSWORD):
    return ServerConfig(email=USER, display_name="Omar Douiri",
                        smtp_host="127.0.0.1", smtp_port=smtp.port, smtp_security=mode,
                        imap_host="127.0.0.1", imap_port=imap.port if imap else 1,
                        username=USER, password=password)


def test_utf7_folder_names():
    assert imap_utf7.decode("&AMk-l&AOk-ments envoy&AOk-s") == "Éléments envoyés"
    assert imap_utf7.decode("Sent &- Archive") == "Sent & Archive"
    for name in ["Éléments envoyés", "Courrier indésirable", "A&B", "INBOX"]:
        assert imap_utf7.decode(imap_utf7.encode(name)) == name


def test_parse_list_response_variants():
    lines = [
        b'(\\HasNoChildren) "." "INBOX"',
        b'(\\HasNoChildren \\Sent) "." "INBOX.Sent"',
        b'(\\Noselect \\HasChildren) "/" Archives',
        (b'(\\HasNoChildren) "/" {16}', b"&AMk-l&AOk-ments"),
        b'(\\HasNoChildren) NIL Spam',
    ]
    folders = parse_list_response(lines)
    names = [f.raw_name for f in folders]
    assert names == ["INBOX", "INBOX.Sent", "Archives", "&AMk-l&AOk-ments", "Spam"]
    assert folders[3].display_name == "Éléments"
    assert folders[2].selectable is False


def test_detect_special_by_flag_then_by_name():
    by_flag = [Folder("INBOX", "INBOX", []), Folder("Mes envois", "Mes envois", ["\\Sent"])]
    assert detect_special(by_flag, "\\Sent", ["sent"]) == "Mes envois"
    by_name = [Folder("INBOX", "INBOX", []), Folder("INBOX.spam", "INBOX.spam", [])]
    assert detect_special(by_name, "\\Junk", ["junk", "inbox.spam"]) == "INBOX.spam"
    assert detect_special(by_name, "\\Sent", ["sent"]) is None


def test_connection_ok_both_smtp_modes(smtp_server, imap_server):
    report = check_connection(_cfg(smtp_server, imap_server, smtp_server.mode))
    assert report.ok, report.steps
    assert [s.label for s in report.steps] == ["SMTP", "Email de test", "IMAP"]
    assert report.sent_folder == "INBOX.Sent"
    assert report.junk_folder == "INBOX.Junk"
    # l'email de test est parti vers soi-même, et seulement vers soi-même
    assert len(smtp_server.messages) == 1
    received = smtp_server.messages[0]
    assert received.rcpt_tos == [USER]
    msg = message_from_bytes(received.data)
    assert msg["Message-ID"].endswith("@oddo.ma>")
    assert "Omar Douiri" in msg["From"]


def test_wrong_password_gives_clear_message(smtp_ssl, imap_server):
    report = check_connection(_cfg(smtp_ssl, imap_server, password="faux"), send_test_email=False)
    assert not report.ok
    details = {s.label: s.detail for s in report.steps}
    assert "mot de passe refusé" in details["SMTP"]
    assert "mot de passe refusé" in details["IMAP"]
    assert smtp_ssl.messages == []


def test_unknown_host_message(smtp_ssl):
    cfg = _cfg(smtp_ssl, None)
    cfg.smtp_host = "serveur-inexistant.invalid"
    report = check_connection(cfg, send_test_email=False)
    assert "introuvable" in report.steps[0].detail


def test_certificate_errors_are_explained():
    import ssl
    from app.mail.transport import explain_error
    exc = ssl.SSLCertVerificationError("hostname mismatch")
    msg = explain_error(exc, "SMTP", "mail.oddo.ma", 465)
    assert "certificat" in msg and "mail.oddo.ma" in msg
    assert "accentué" in explain_error(UnicodeEncodeError("ascii", "é", 0, 1, "x"), "IMAP", "h", 993)

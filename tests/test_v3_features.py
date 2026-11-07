"""V3 : petites finitions (spam, aperçu des pièces jointes, prochains envois, cotations par branche)."""
import io

import pytest

from tests.fakes.fake_imap import FakeFolder
from tests.test_m4_engine import world  # noqa: F401
from tests.test_v219 import _uid, box  # noqa: F401

O = {"Origin": "http://testserver"}


@pytest.mark.parametrize("existing", [None, "INBOX.spam", "INBOX.Junk"])
def test_spam_moves_to_junk_and_undo(client, box, existing):  # noqa: F811
    imap = box["imap"]
    imap.capabilities = "IMAP4rev1 MOVE UIDPLUS"
    imap.folders.pop("INBOX.Junk", None)   # le faux serveur en a un par défaut
    if existing:
        imap.folders[existing] = FakeFolder(flags=[])
    uid = _uid(client, "Avenant")
    r = client.post(f"/api/mailbox/messages/{uid}/spam?folder=INBOX", headers=O)
    assert r.status_code == 200, r.text
    dest = r.json()["archive_folder"]
    assert dest == (existing or "INBOX.Junk")
    assert len(imap.folders[dest].messages) == 1 and not imap.folders["INBOX"].messages
    assert sum(1 for n in imap.folders if n.lower().endswith(("junk", "spam"))) == 1   # pas de doublon
    back = client.post("/api/mailbox/unarchive", json={"message_id": r.json()["message_id"], "folder": "INBOX", "kind": "junk"}, headers=O)
    assert back.status_code == 200 and not imap.folders[dest].messages and len(imap.folders["INBOX"].messages) == 1


def test_spam_uses_flagged_junk_folder(client, box):  # noqa: F811
    imap = box["imap"]
    imap.capabilities = "IMAP4rev1 MOVE UIDPLUS"
    imap.folders.pop("INBOX.Junk", None)
    imap.folders["INBOX.spam"] = FakeFolder(flags=[])                     # nom reconnu, mais…
    imap.folders["Pourriels"] = FakeFolder(flags=["\\Junk"])  # …le dossier marqué \Junk passe avant
    uid = _uid(client, "Avenant")
    assert client.post(f"/api/mailbox/messages/{uid}/spam?folder=INBOX", headers=O).json()["archive_folder"] == "Pourriels"


def _docx(text: str) -> bytes:
    import zipfile
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("[Content_Types].xml", '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                   '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
                   '<Default Extension="xml" ContentType="application/xml"/>'
                   '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>')
        z.writestr("_rels/.rels", '<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                   '<Relationship Id="r1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>')
        z.writestr("word/document.xml", '<?xml version="1.0"?><w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
                   f'<w:body><w:p><w:r><w:t>{text}</w:t></w:r></w:p></w:body></w:document>')
    return buf.getvalue()


def _xlsx() -> bytes:
    import openpyxl
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["Immatriculation", "Usage"])
    ws.append(["12345-A-6", "<script>x</script>"])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_attachment_preview_kinds(client, world):  # noqa: F811
    from email.message import EmailMessage

    from app import mailbox_browser
    from app.timeutil import utcnow
    from tests.conftest import USER
    m = EmailMessage()
    m["From"], m["To"], m["Subject"], m["Message-ID"] = "c@client.ma", USER, "Docs flotte", "<docs@client.ma>"
    m.set_content("Ci-joint.")
    m.add_attachment(_docx("Conditions particulières flotte"), maintype="application",
                     subtype="vnd.openxmlformats-officedocument.wordprocessingml.document", filename="CP.docx")
    m.add_attachment(_xlsx(), maintype="application", subtype="octet-stream", filename="parc.xlsx")
    m.add_attachment("nom;prenom\nAlaoui;Sara\n".encode(), maintype="text", subtype="csv", filename="liste.csv")
    m.add_attachment(b"%PDF-1.4 x", maintype="application", subtype="pdf", filename="releve.pdf")
    m.add_attachment(b"\xd0\xcf\x11\xe0 old", maintype="application", subtype="msword", filename="ancien.doc")
    mailbox_browser.invalidate()
    world["imap"].deliver("INBOX", m.as_bytes(), utcnow().date())
    uid = client.get("/api/mailbox/messages?folder=INBOX&days=30&refresh=1").json()["items"][0]["uid"]
    atts = {a["name"]: a for a in client.get(f"/api/mailbox/messages/{uid}?folder=INBOX").json()["attachments"]}
    assert [n for n, a in atts.items() if a["previewable"]] == ["CP.docx", "parc.xlsx", "liste.csv", "releve.pdf"]

    def pv(name):
        return client.get(f"/api/mailbox/messages/{uid}/preview/{atts[name]['index']}?folder=INBOX").json()
    d = pv("CP.docx")
    assert d["kind"] == "html" and "Conditions particulières flotte" in d["html"]
    x = pv("parc.xlsx")
    assert x["kind"] == "html" and "12345-A-6" in x["html"] and "<script>" not in x["html"] and "&lt;script&gt;" in x["html"]
    c = pv("liste.csv")
    assert c["kind"] == "html" and "<td>Alaoui</td>" in c["html"]
    assert pv("releve.pdf")["kind"] == "pdf"
    assert pv("ancien.doc")["kind"] == "none"
    mailbox_browser.invalidate()


def test_campaign_upcoming_matches_what_the_engine_sends(client, world):  # noqa: F811
    """« Prochains envois » d'une campagne : exactement ce que le moteur enverra (objet, texte,
    signature), puis, après le 1er email, les relances restantes « Re: » du même fil."""
    from datetime import timedelta
    from email import message_from_bytes, policy

    from tests.test_m4_engine import START, _activate, _run
    cid = world["campaign_id"]
    n = _activate(cid)
    up = client.get(f"/api/campaigns/{cid}/upcoming").json()
    assert up["total"] == n and len(up["items"]) == n
    first = {it["to"]: it["emails"][0] for it in up["items"]}
    n_steps = len(up["items"][0]["emails"])
    assert n_steps >= 2 and all(e["planned_at"] for e in up["items"][0]["emails"])
    _run(until=START + timedelta(hours=10))  # les premiers emails partent
    sent = [message_from_bytes(m.data, policy=policy.default) for m in world["smtp"].messages]
    assert sent
    for msg in sent:
        to = str(msg["To"]).split("<")[-1].rstrip(">").strip().lower()
        if to in first:
            assert str(msg["Subject"]).endswith(first[to]["subject"]) or first[to]["subject"] in str(msg["Subject"])
            assert first[to]["body"].split("\n")[0].strip() in msg.get_body(preferencelist=("plain",)).get_content()
    after = client.get(f"/api/campaigns/{cid}/upcoming").json()
    done = [it for it in after["items"] if it["emails"][0]["position"] == 2]
    assert done and all(e["subject"].lower().startswith("re") for it in done for e in it["emails"] if e["same_thread"])
    assert all(len(it["emails"]) == n_steps - 1 for it in done)


def test_quotation_templates_by_branch_ready_at_first_open(client, db):
    """Les 10 demandes de cotation par branche sont là dès la première ouverture, communes à
    l'équipe, rangées par branche ; AT et prévoyance demandent les bons éléments."""
    from app import starter_data
    from app.db import get_session
    with get_session() as s:
        starter_data.apply_sequences(s)
        s.commit()
    items = client.get("/api/sequences").json()["items"]
    cot = {q["branch"]: q for q in items if q["category"] == "souscription" and q["branch"]}
    assert set(cot) == {"Flotte", "Accidents du travail", "Prévoyance", "Retraite", "RC professionnelle", "RC exploitation",
                        "Multirisque", "Multirisque habitation", "Transport", "Tous risques chantier"}
    at = client.get(f"/api/sequences/{cot['Accidents du travail']['id']}").json()
    body = at["steps"][0]["body"]
    assert "[Effectif]" in body and "[Masse salariale]" in body and "[Activité]" in body and at["shared"] is True
    prv = client.get(f"/api/sequences/{cot['Prévoyance']['id']}").json()["steps"][0]["body"]
    assert "AMC" in prv and "DIM" in prv and "conjoints" in prv and "enfants" in prv
    # la branche se change dans l'éditeur, et se garde à la duplication
    dup = client.post(f"/api/sequences/{cot['Retraite']['id']}/duplicate", headers=O).json()
    assert client.get(f"/api/sequences/{dup['id']}").json()["branch"] == "Retraite"

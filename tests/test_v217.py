"""V2.17 : mise à jour depuis le lien du kit (téléchargement, contrôle, installation sans
toucher au dossier data), boîte relue toutes les 5 minutes."""
import io
import zipfile
from datetime import timedelta

import pytest

from app import VERSION, imap_sync, updater

ORIGIN = {"Origin": "http://testserver"}


def kit(version="9.9.0", extra=None, prefix="ODDO-Sequences/"):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr(prefix + "app/__init__.py", f'HOST = "127.0.0.1"\nVERSION = "{version}"\n')
        z.writestr(prefix + "app/nouveau.py", "X = 1\n")
        z.writestr(prefix + "app/__pycache__/x.pyc", b"\0")
        z.writestr(prefix + "migrations/versions/0009.py", "# migration\n")
        z.writestr(prefix + "requirements.txt", "fastapi\n")
        z.writestr(prefix + "start.bat", "@echo off\r\nREM nouveau\r\n")
        z.writestr(prefix + "data/oddo.db", b"PAS TOUCHE")
        z.writestr(prefix + "tests/test_x.py", "")
        for name, data in (extra or {}).items():
            z.writestr(prefix + name, data)
    return buf.getvalue()


def test_sync_every_5_minutes():
    assert imap_sync.STALE_AFTER == timedelta(minutes=5)


def test_download_url():
    u = updater.download_url("https://drive.google.com/file/d/1AbCdEfGhIjKlMnOpQrStUvWxYz012345/view?usp=sharing")
    assert u == "https://drive.usercontent.google.com/download?id=1AbCdEfGhIjKlMnOpQrStUvWxYz012345&export=download&confirm=t"
    assert updater.download_url("https://exemple.ma/kit.zip") == "https://exemple.ma/kit.zip"
    with pytest.raises(updater.UpdateError):
        updater.download_url("http://exemple.ma/kit.zip")
    assert updater.parse_version("2.17.0") > updater.parse_version("2.9.3")


def test_apply_zip(tmp_path):
    root = tmp_path / "ODDO"
    (root / "app").mkdir(parents=True)
    (root / "data").mkdir()
    (root / "data" / "oddo.db").write_bytes(b"MA BASE")
    (root / "start.bat").write_text("@echo off\r\nREM ancien\r\n")
    (root / "requirements.txt").write_text("fastapi\n")
    p = tmp_path / "k.zip"
    p.write_bytes(kit())
    r = updater.apply_zip(p, root)
    assert r["version"] == "9.9.0" and r["deferred"] == ["start.bat"]
    assert (root / "app" / "nouveau.py").read_text() == "X = 1\n"
    assert (root / "migrations" / "versions" / "0009.py").exists()
    assert (root / "data" / "oddo.db").read_bytes() == b"MA BASE"       # jamais touché
    assert not (root / "tests").exists() and not (root / "app" / "__pycache__").exists()
    assert "ancien" in (root / "start.bat").read_text()                   # remplacé au redémarrage
    assert "nouveau" in (root / "start.bat.new").read_text()


def test_apply_zip_rejects_escape(tmp_path):
    p = tmp_path / "k.zip"
    p.write_bytes(kit(extra={"app/../../evil.py": "x"}))
    with pytest.raises(updater.UpdateError):
        updater.apply_zip(p, tmp_path / "ODDO")
    assert not (tmp_path / "evil.py").exists() and not (tmp_path / "ODDO" / "app").exists()


@pytest.mark.sqlite_only  # V3 : mise à jour par zip = poste unique (fermée sur le serveur)
def test_check_and_install(client, db, tmp_path, monkeypatch):
    root = tmp_path / "ODDO"
    root.mkdir()
    monkeypatch.setattr(updater, "PROJECT_DIR", root)
    payload = {"data": kit("9.9.0")}

    def fake_fetch(url, dest):
        dest.write_bytes(payload["data"])
        return dest
    monkeypatch.setattr(updater, "fetch", fake_fetch)
    monkeypatch.setattr(updater, "DEFAULT_UPDATE_URL", ""); assert client.post("/api/update/check", headers=ORIGIN).json()["error"] == "Aucun lien de mise à jour réglé."
    assert client.post("/api/update/url", json={"url": "ftp://x"}, headers=ORIGIN).status_code == 400
    r = client.post("/api/update/url", json={"url": "https://drive.google.com/file/d/1AbCdEfGhIjKlMnOpQrStUvWxYz012345/view"},
                    headers=ORIGIN).json()
    assert r["url"].startswith("https://drive.google.com")
    st = client.post("/api/update/check", headers=ORIGIN).json()
    assert st["newer"] and st["available"] == "9.9.0" and st["current"] == VERSION
    notes = client.get("/api/notifications").json()["items"]
    assert any(n["type"] == "update" for n in notes)
    rep = client.post("/api/update/install", headers=ORIGIN).json()
    assert rep["version"] == "9.9.0" and rep["restarting"] is False
    assert (root / "app" / "nouveau.py").exists()
    assert client.post("/api/update/install", headers=ORIGIN).status_code == 400  # plus rien à installer
    # Même version que l'actuelle : rien à proposer
    payload["data"] = kit(VERSION)
    st = client.post("/api/update/check", headers=ORIGIN).json()
    assert not st["newer"] and st["available"] == VERSION and not st["error"]


@pytest.mark.sqlite_only
def test_check_bad_file(client, db, monkeypatch):
    def fake_fetch(url, dest):
        raise updater.UpdateError("Le lien ne donne pas un fichier .zip")
    monkeypatch.setattr(updater, "fetch", fake_fetch)
    client.post("/api/update/url", json={"url": "https://drive.google.com/file/d/1AbCdEfGhIjKlMnOpQrStUvWxYz012345/view"}, headers=ORIGIN)
    st = client.post("/api/update/check", headers=ORIGIN).json()
    assert not st["newer"] and "zip" in st["error"]


def test_contact_filters_by_kind(client, db):
    from app import companies_service as co
    from app.models import Contact
    from app.db import get_session
    with get_session() as s:
        wafa, _ = co.get_or_create(s, "Wafa Assurance", "insurer")
        axa, _ = co.get_or_create(s, "AXA Assurance Maroc", "insurer")
        s.add_all([Contact(email="a@wafa.ma", kind="insurer", company="Wafa Assurance", company_id=wafa.id, department="gestion", seniority="senior"),
                   Contact(email="b@wafa.ma", kind="insurer", company="Wafa Assurance", company_id=wafa.id, department="souscription", seniority="junior"),
                   Contact(email="c@axa.ma", kind="insurer", company="AXA Assurance Maroc", company_id=axa.id, department="gestion", seniority="directeur"),
                   Contact(email="p@x.ma", kind="prospect", target_segment="DIR")])
        s.commit()
        wid, aid = wafa.id, axa.id
    d = client.get("/api/contacts", params={"kind": "insurer"}).json()
    assert [o["label"] for o in d["options"]["companies_by_kind"]["insurer"]] == ["AXA Assurance Maroc", "Wafa Assurance"]
    assert set(d["options"]["department"]) == {"gestion", "souscription"}
    rows = client.get("/api/contacts", params={"kind": "insurer", "company_id": wid, "department": "gestion"}).json()["items"]
    assert [r["email"] for r in rows] == ["a@wafa.ma"]
    rows = client.get("/api/contacts", params={"kind": "insurer", "seniority": "directeur"}).json()["items"]
    assert [r["email"] for r in rows] == ["c@axa.ma"] and aid

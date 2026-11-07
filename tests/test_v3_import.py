"""V3 : reprise des données de la V2 (paquet .zip) sur le serveur."""
import io
import zipfile
from datetime import date

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from app.db import get_session
from app.models import Campaign, Contact, Enrollment, Mailbox, Reminder, Sequence, Setting
from tests.test_v3_auth import H, server  # noqa: F401  (fixture)


def _pack(tmp_path) -> bytes:
    """Base V2 réaliste : migrations SQLite puis quelques données, comme sur le PC d'Omar."""
    from app import import_v2
    db = tmp_path / "v2" / "oddo.db"
    db.parent.mkdir()
    import_v2._upgrade_sqlite(db)
    eng = create_engine(f"sqlite:///{db}")
    with Session(eng) as s, s.begin():
        mb = Mailbox(display_name="Omar", email="omar@oddo.ma", smtp_host="smtp.test")
        seq = Sequence(name="Prospection V2")
        prospect = Contact(email="client@prospect.ma", kind="prospect")
        idle = Contact(email="jamais@prospect.ma", kind="prospect")
        insurer = Contact(email="agent@assureur.ma", kind="insurer")
        s.add_all([mb, seq, prospect, idle, insurer])
        s.flush()
        camp = Campaign(name="Campagne V2", mailbox_id=mb.id, sequence_id=seq.id, status="active")
        s.add(camp)
        s.flush()
        s.add(Enrollment(campaign_id=camp.id, contact_id=prospect.id))
        s.add(Reminder(title="Rappeler", due_on=date(2026, 12, 1)))
        s.add_all([Setting(key="test_mode", value="false"), Setting(key="holidays", value="[]"),
                   Setting(key="update_url", value='"https://ancien"')])
    eng.dispose()
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.write(db, "oddo.db")
        z.writestr("attachments/tok123/brochure.pdf", b"%PDF-1.4 test")
        z.writestr("../evil.txt", b"x")
    return buf.getvalue()


def test_import_v2_pack(server, tmp_path):  # noqa: F811
    data = _pack(tmp_path)
    files = {"file": ("donnees-v2.zip", data, "application/zip")}
    assert server.post("/api/admin/import-v2", files=files, headers=H("hamza@oddo.ma")).status_code == 403
    r = server.post("/api/admin/import-v2", files=files, headers=H("omar@oddo.ma"))
    assert r.status_code == 200, r.text
    assert r.json()["counts"]["campaign"] == 1 and r.json()["files"] == 1
    me = server.get("/api/me", headers=H("omar@oddo.ma")).json()
    with get_session() as s:
        assert s.scalar(select(Mailbox.user_id)) == me["id"]
        owners = dict(s.execute(select(Contact.email, Contact.owner_id)).all())
        assert owners["client@prospect.ma"] == me["id"]       # déjà contacté : à Omar
        assert owners["jamais@prospect.ma"] is None           # jamais contacté : libre
        assert owners["agent@assureur.ma"] is None            # assureur : commun
        assert s.scalar(select(Reminder.user_id)) == me["id"]
        keys = set(s.scalars(select(Setting.key)))
        assert f"u{me['id']}:test_mode" in keys and "holidays" in keys and not any("update_url" in k for k in keys)
        new = Contact(email="apres@import.ma", kind="prospect")  # numérotation repartie après les ids importés
        s.add(new)
        s.commit()
    from app.paths import data_dir
    assert (data_dir() / "attachments" / "tok123" / "brochure.pdf").exists()
    assert not (data_dir().parent / "evil.txt").exists()
    # Omar voit sa campagne, Hamza non
    camps = lambda who: server.get("/api/campaigns", headers=H(who)).json()  # noqa: E731
    items = lambda d: d["items"] if isinstance(d, dict) else d  # noqa: E731
    assert len(items(camps("omar@oddo.ma"))) == 1
    assert items(camps("hamza@oddo.ma")) == []
    # deuxième import : refusé (écraserait le travail), sauf remplacement demandé
    assert server.post("/api/admin/import-v2", files=files, headers=H("omar@oddo.ma")).status_code == 409
    with get_session() as s:
        assert s.scalar(select(func.count()).select_from(Campaign).execution_options(oddo_all=True)) == 1


def test_import_rejects_bad_files(server):  # noqa: F811
    bad = {"file": ("x.zip", b"pas un zip", "application/zip")}
    r = server.post("/api/admin/import-v2", files=bad, headers=H("omar@oddo.ma"))
    assert r.status_code == 400 and "zip" in r.json()["detail"]
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("autre.txt", b"x")
    r = server.post("/api/admin/import-v2", files={"file": ("x.zip", buf.getvalue(), "application/zip")}, headers=H("omar@oddo.ma"))
    assert r.status_code == 400 and "oddo.db" in r.json()["detail"]

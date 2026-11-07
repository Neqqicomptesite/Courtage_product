"""V3 : reprise des données de la V2 (poste unique, SQLite) dans la base du serveur.

L'administrateur envoie un « paquet » .zip (fabriqué depuis son PC) contenant :
    oddo.db            copie cohérente de la base SQLite de la V2
    attachments/...    pièces jointes (facultatif)
    logos/...          logos des compagnies (facultatif)

Tout se fait dans UNE transaction : en cas d'erreur, la base du serveur reste comme avant.
Les données de départ créées au premier démarrage du serveur (assureurs, modèles) sont
remplacées par celles de la V2, qui les contiennent déjà (avec les modifications d'Omar).
Le mot de passe de la boîte mail n'est pas dans la base (Gestionnaire Windows) : il faut le
ressaisir dans Réglages.
"""
from __future__ import annotations

import io
import shutil
import sqlite3
import tempfile
import zipfile
from pathlib import Path, PurePosixPath

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, delete, func, insert, select, text, update

from app import models  # noqa: F401
from app.db import Base, get_session
from app.paths import PROJECT_DIR, data_dir
from app.settings_store import GLOBAL_KEYS

KEEP = {"app_user", "secret"}          # comptes du serveur : jamais touchés
FILE_DIRS = ("attachments", "logos")   # dossiers de fichiers repris
MAX_UNZIPPED = 300 * 1024 * 1024


class ImportError_(ValueError):
    pass


def _upgrade_sqlite(path: Path) -> None:
    """Met la copie de la base V2 au même niveau que le code (migrations SQLite habituelles)."""
    cfg = Config(str(PROJECT_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(PROJECT_DIR / "migrations"))
    cfg.attributes["db_url"] = f"sqlite:///{path}"
    command.upgrade(cfg, "head")


def _extract(data: bytes, dest: Path) -> Path:
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise ImportError_("Ce fichier n'est pas un paquet .zip valide.") from exc
    if sum(i.file_size for i in zf.infolist()) > MAX_UNZIPPED:
        raise ImportError_("Paquet trop volumineux.")
    db = None
    for info in zf.infolist():
        name = PurePosixPath(info.filename.replace("\\", "/"))
        if info.is_dir() or name.is_absolute() or ".." in name.parts:
            continue
        if name.name == "oddo.db" and len(name.parts) <= 2:
            db = dest / "oddo.db"
            db.write_bytes(zf.read(info))
            continue
        # fichiers : <attachments|logos>/... éventuellement sous un dossier racine
        parts = name.parts[1:] if name.parts[0] not in FILE_DIRS and len(name.parts) > 1 else name.parts
        if parts and parts[0] in FILE_DIRS:
            out = dest.joinpath("files", *parts)
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(zf.read(info))
    if db is None:
        raise ImportError_("Le paquet ne contient pas de fichier oddo.db.")
    try:
        con = sqlite3.connect(db)
        try:
            con.execute("SELECT 1 FROM alembic_version").fetchone()
            ok = con.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        finally:
            con.close()
    except sqlite3.Error as exc:
        raise ImportError_("oddo.db n'est pas une base ODDO Séquences lisible.") from exc
    if not ok:
        raise ImportError_("oddo.db est endommagée (contrôle d'intégrité en échec).")
    return db


def existing_work() -> int:
    """Campagnes + messages déjà présents sur le serveur (pour éviter d'écraser du travail)."""
    with get_session() as s:
        n = s.scalar(select(func.count()).select_from(models.Campaign).execution_options(oddo_all=True)) or 0
        n += s.scalar(select(func.count()).select_from(models.Message).execution_options(oddo_all=True)) or 0
        return n


def import_pack(data: bytes, admin_uid: int) -> dict:
    tmp = Path(tempfile.mkdtemp(prefix="oddo-import-"))
    try:
        db = _extract(data, tmp)
        _upgrade_sqlite(db)
        src = create_engine(f"sqlite:///{db}")
        tables = [t for t in Base.metadata.sorted_tables if t.name not in KEEP]
        rows: dict[str, list[dict]] = {}
        with src.connect() as c:
            for t in tables:
                rows[t.name] = [dict(r._mapping) for r in c.execute(select(t))]
        src.dispose()

        # --- rattacher les données à l'administrateur (Omar) ---------------------------------
        boxes = rows.get("mailbox", [])
        for b in boxes:
            b["user_id"] = None
        if boxes:
            boxes[0]["user_id"] = admin_uid  # V2 : une seule boîte, celle d'Omar
        box_id = boxes[0]["id"] if boxes else None
        for m in rows.get("message", []):
            if m.get("mailbox_id") is None:
                m["mailbox_id"] = box_id
        for r in rows.get("reminder", []):
            r["user_id"] = admin_uid
        contacted = {e["contact_id"] for e in rows.get("enrollment", [])} | \
                    {m["contact_id"] for m in rows.get("message", []) if m.get("contact_id")}
        for ct in rows.get("contact", []):
            if ct.get("kind") == "prospect" and ct["id"] in contacted and not ct.get("owner_id"):
                ct["owner_id"] = admin_uid
        settings = []
        for st in rows.get("setting", []):
            key = st["key"]
            if ":" in key or key in ("update_url", "update_status"):
                continue  # mises à jour : gérées par le serveur
            settings.append({"key": key if key in GLOBAL_KEYS else f"u{admin_uid}:{key}", "value": st["value"]})
        rows["setting"] = settings

        # --- remplacer le contenu du serveur, en une transaction -----------------------------
        with get_session() as s, s.begin():
            for t in reversed(tables):
                s.execute(delete(t))
            for t in tables:
                if rows[t.name]:
                    s.execute(insert(t), rows[t.name])
            if s.bind.dialect.name == "postgresql":
                for t in tables:
                    if "id" in t.c and t.c.id.primary_key and t.c.id.autoincrement is not False:
                        s.execute(text(f"SELECT setval(pg_get_serial_sequence('{t.name}', 'id'), "
                                       f"COALESCE((SELECT MAX(id) FROM {t.name}), 0) + 1, false)"))
            s.execute(update(models.Mailbox).where(models.Mailbox.id != box_id).values(user_id=None))

        # --- fichiers ------------------------------------------------------------------------
        n_files = 0
        for d in FILE_DIRS:
            srcdir = tmp / "files" / d
            if srcdir.is_dir():
                for f in srcdir.rglob("*"):
                    if f.is_file():
                        out = data_dir() / d / f.relative_to(srcdir)
                        out.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(f, out)
                        n_files += 1
        from app import scope
        scope.forget_cache()
        return {"counts": {t.name: len(rows[t.name]) for t in tables if rows[t.name]}, "files": n_files,
                "mailbox": boxes[0]["email"] if boxes else None}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

"""Sauvegardes de data/oddo.db (au démarrage, chaque jour, avant une restauration ou une mise à jour).

On utilise l'API « backup » de SQLite plutôt qu'une simple copie de fichier :
une copie pendant une écriture pourrait produire un fichier corrompu, et avec
le mode WAL une partie des données est dans un fichier à côté (oddo.db-wal).

V2.20 :
- on garde les 10 plus récentes ET la plus récente de chaque jour sur 30 jours (avant : les
  14 dernières seulement, si bien qu'une journée de redémarrages effaçait les jours précédents) ;
- « quotidienne » : vérifiée toutes les heures, faite si la dernière date de plus de 20 heures
  (avant : 23:00 précises, jamais faite si le PC était éteint à cette heure-là) ;
- copie facultative dans un second dossier (Google Drive, OneDrive, clé…) choisi dans Réglages,
  pour ne pas tout perdre si le PC tombe en panne.
"""
import logging
import re
import shutil
import sqlite3
from datetime import date, timedelta
from pathlib import Path

from app.paths import backups_dir, db_path
from app.timeutil import to_local, utcnow

KEEP = 10          # les plus récentes, quoi qu'il arrive
KEEP_DAYS = 30     # plus une par jour sur cette période
DAILY_AFTER_H = 20
log = logging.getLogger(__name__)
_NAME = re.compile(r"^oddo_(\d{4})-(\d{2})-(\d{2})_(\d{6})_.*\.db$")


def copy_dir() -> str:
    """Second dossier de sauvegarde (réglage « backup_copy_dir »), lu directement dans la base :
    la sauvegarde du démarrage a lieu avant les migrations et l'ouverture de la session."""
    try:
        con = sqlite3.connect(db_path())
        try:
            row = con.execute("SELECT value FROM setting WHERE key = 'backup_copy_dir'").fetchone()
        finally:
            con.close()
    except sqlite3.Error:
        return ""
    if not row or not row[0]:
        return ""
    import json
    try:
        return str(json.loads(row[0]) or "")
    except ValueError:
        return ""


def backup_now(label: str = "auto") -> Path | None:
    src_path = db_path()
    if not src_path.exists():
        return None
    backups_dir().mkdir(parents=True, exist_ok=True)
    stamp = to_local(utcnow()).strftime("%Y-%m-%d_%H%M%S")
    dest_path = backups_dir() / f"oddo_{stamp}_{label}.db"
    src = sqlite3.connect(src_path)
    dest = sqlite3.connect(dest_path)
    try:
        src.backup(dest)
    finally:
        dest.close()
        src.close()
    _prune(backups_dir(), protect=dest_path)
    log.info("Sauvegarde créée : %s", dest_path.name)
    _copy_offsite(dest_path)
    return dest_path


def _copy_offsite(path: Path) -> None:
    target = copy_dir()
    if not target:
        return
    try:
        d = Path(target)
        if not d.is_dir():
            raise OSError(f"dossier introuvable : {target}")
        shutil.copy2(path, d / path.name)
        _prune(d, protect=d / path.name)
    except OSError as e:  # jamais bloquant : la sauvegarde locale existe
        log.warning("Copie de la sauvegarde dans %s impossible : %s", target, e)


def _day(p: Path) -> date | None:
    m = _NAME.match(p.name)
    return date(int(m[1]), int(m[2]), int(m[3])) if m else None


def _prune(folder: Path, protect: Path | None = None) -> None:
    """V2.23 : la sauvegarde qu'on vient de faire n'est jamais supprimée, même si l'horloge du PC
    a reculé (changement d'heure, horloge corrigée) et que d'autres paraissent plus récentes."""
    files = sorted(folder.glob("oddo_*.db"), key=lambda p: p.name)
    keep = set(files[-KEEP:])
    if protect is not None and protect not in keep:
        keep = set(files[-(KEEP - 1):]) | {protect}  # toujours KEEP au total
    limit = to_local(utcnow()).date() - timedelta(days=KEEP_DAYS)
    seen: set[date] = set()
    for p in reversed(files):  # la plus récente de chaque jour
        d = _day(p)
        if d and d >= limit and d not in seen:
            seen.add(d)
            keep.add(p)
    for old in files:
        if old not in keep:
            old.unlink(missing_ok=True)


def latest() -> Path | None:
    files = sorted(backups_dir().glob("oddo_*.db"), key=lambda p: p.name)
    return files[-1] if files else None


def daily_if_due() -> Path | None:
    last = latest()
    if last is not None:
        age_h = (utcnow().timestamp() - last.stat().st_mtime) / 3600
        if age_h < DAILY_AFTER_H:
            return None
    return backup_now("quotidienne")


def listing() -> list[dict]:
    out = []
    for p in sorted(backups_dir().glob("oddo_*.db"), key=lambda p: p.name, reverse=True):
        m = _NAME.match(p.name)
        if not m:
            continue
        label = p.name[len("oddo_YYYY-MM-DD_HHMMSS_"):-3]
        out.append({"name": p.name, "date": f"{m[1]}-{m[2]}-{m[3]}T{m[4][:2]}:{m[4][2:4]}:{m[4][4:]}",
                    "label": label, "size": p.stat().st_size})
    return out

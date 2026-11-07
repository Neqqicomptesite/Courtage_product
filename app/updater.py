"""Mise à jour de l'application depuis un lien fixe (V2.17).

Principe : Omar dépose le kit (ODDO-Sequences-kit.zip) sur son Google Drive, partagé
« Tous les utilisateurs qui ont le lien ». À chaque nouvelle version, il remplace le contenu
de CE fichier (Drive → Gérer les versions → Importer une nouvelle version) : le lien ne change
pas. Chaque application télécharge le fichier, lit son numéro de version, et propose
« Installer et redémarrer » s'il est plus récent.

Sécurité des données : on ne touche JAMAIS au dossier data (base, sauvegardes, pièces jointes,
logos) ni à .venv ; la base est sauvegardée juste avant ; seuls les fichiers de l'application
connus sont écrits (app/, migrations/, quelques fichiers à la racine), sans jamais sortir du
dossier de l'application. Les fichiers .bat sont remplacés après l'arrêt (Windows lit un .bat
en cours d'exécution au fil de l'eau : le réécrire pendant qu'il tourne le casserait).
"""
from __future__ import annotations

import logging
import os
import re
import subprocess
import sys
import threading
import urllib.request
import zipfile
from pathlib import Path, PurePosixPath

from app import VERSION, settings_store
from app.paths import PROJECT_DIR, data_dir
from app.timeutil import utcnow

log = logging.getLogger(__name__)

# Lien du kit sur le Drive d'Omar (réglable dans Réglages → Mise à jour).
DEFAULT_UPDATE_URL = "https://drive.google.com/file/d/1GbB-if9Kno80a8_aFbzc1gHHDVrpLFPA/view"
MAX_BYTES = 60 * 1024 * 1024
ROOT_FILES = {"requirements.txt", "alembic.ini", "README.md", "LISEZ-MOI-INSTALLATION.html",
              "start.bat", "restaurer_sauvegarde.bat"}
ROOT_DIRS = {"app", "migrations"}
DEFERRED = {"start.bat", "restaurer_sauvegarde.bat"}  # remplacés après l'arrêt de l'application
VERSION_RE = re.compile(r'^VERSION\s*=\s*"([0-9]+(?:\.[0-9]+)*)"', re.M)
_lock = threading.Lock()


class UpdateError(Exception):
    pass


def updates_dir() -> Path:
    d = data_dir() / "updates"
    d.mkdir(parents=True, exist_ok=True)
    return d


def parse_version(v: str) -> tuple[int, ...]:
    return tuple(int(x) for x in re.findall(r"\d+", v or "0"))


def configured_url(s) -> str:
    return (settings_store.get(s, "update_url") or DEFAULT_UPDATE_URL or "").strip()


def download_url(url: str) -> str:
    """Lien de partage Google Drive → lien de téléchargement direct ; autre lien https : tel quel."""
    url = url.strip()
    m = re.search(r"/d/([A-Za-z0-9_-]{20,})", url) or re.search(r"[?&]id=([A-Za-z0-9_-]{20,})", url)
    if "google.com" in url and m:
        return f"https://drive.usercontent.google.com/download?id={m.group(1)}&export=download&confirm=t"
    if not url.lower().startswith("https://"):
        raise UpdateError("Le lien doit commencer par https:// (lien de partage Google Drive).")
    return url


def fetch(url: str, dest: Path) -> Path:
    req = urllib.request.Request(download_url(url), headers={"User-Agent": "ODDO-Sequences-updater"})
    tmp = dest.with_suffix(".part")
    size = 0
    try:
        with urllib.request.urlopen(req, timeout=60) as r, open(tmp, "wb") as out:
            while chunk := r.read(256 * 1024):
                size += len(chunk)
                if size > MAX_BYTES:
                    raise UpdateError("Fichier trop gros pour être un kit ODDO Séquences.")
                out.write(chunk)
    except UpdateError:
        tmp.unlink(missing_ok=True)
        raise
    except Exception as e:  # noqa: BLE001 – réseau, DNS, certificat…
        tmp.unlink(missing_ok=True)
        raise UpdateError(f"Téléchargement impossible : vérifiez la connexion internet ({e})") from e
    if not zipfile.is_zipfile(tmp):
        tmp.unlink(missing_ok=True)
        raise UpdateError("Le lien ne donne pas un fichier .zip : vérifiez qu'il est partagé "
                          "« Tous les utilisateurs qui ont le lien ».")
    tmp.replace(dest)
    return dest


def inspect(path: Path) -> tuple[str, str]:
    """(version, préfixe) du kit : le préfixe est le dossier qui contient app/__init__.py."""
    with zipfile.ZipFile(path) as z:
        inits = sorted((n for n in z.namelist() if n.endswith("app/__init__.py")), key=len)
        if not inits:
            raise UpdateError("Ce fichier n'est pas un kit ODDO Séquences.")
        prefix = inits[0][: -len("app/__init__.py")]
        m = VERSION_RE.search(z.read(inits[0]).decode("utf-8", "replace"))
        if not m:
            raise UpdateError("Numéro de version introuvable dans le kit.")
        return m.group(1), prefix


def _status(s) -> dict:
    st = settings_store.get(s, "update_status") or {}
    available = st.get("available")
    return {"current": VERSION, "url": configured_url(s), "checked_at": st.get("checked_at"),
            "available": available, "error": st.get("error"),
            "newer": bool(available and parse_version(available) > parse_version(VERSION)
                          and (updates_dir() / "latest.zip").is_file())}


def status() -> dict:
    from app.db import get_session
    with get_session() as s:
        return _status(s)


def check() -> dict:
    """Télécharge le kit et compare les versions. Ne bloque jamais l'application."""
    from app.db import get_session
    with _lock:
        with get_session() as s:
            url = configured_url(s)
        result: dict = {"checked_at": utcnow().isoformat(), "available": None, "error": None}
        if not url:
            result["error"] = "Aucun lien de mise à jour réglé."
        else:
            try:
                path = fetch(url, updates_dir() / "download.zip")
                version, _ = inspect(path)
                result["available"] = version
                if parse_version(version) > parse_version(VERSION):
                    path.replace(updates_dir() / "latest.zip")
                else:
                    path.unlink(missing_ok=True)
            except UpdateError as e:
                result["error"] = str(e)
        with get_session() as s:
            settings_store.set_(s, "update_status", result)
            s.commit()
            out = _status(s)
        if result["error"]:
            log.warning("Vérification des mises à jour : %s", result["error"])
        return out


def _safe_target(root: Path, rel: str) -> Path | None:
    p = PurePosixPath(rel)
    if p.is_absolute() or ".." in p.parts or not p.parts:
        raise UpdateError(f"Chemin refusé dans le kit : {rel}")
    if p.parts[0] in ROOT_DIRS or (len(p.parts) == 1 and p.parts[0] in ROOT_FILES):
        if "__pycache__" in p.parts:
            return None
        target = (root / Path(*p.parts)).resolve()
        if root.resolve() not in target.parents:
            raise UpdateError(f"Chemin refusé dans le kit : {rel}")
        return target
    return None  # data/, .venv/, tests… : jamais touchés


def apply_zip(path: Path, root: Path | None = None) -> dict:
    """Écrit les fichiers du kit dans le dossier de l'application. Renvoie un résumé."""
    root = root or PROJECT_DIR
    version, prefix = inspect(path)
    written, deferred = 0, []
    with zipfile.ZipFile(path) as z:
        members = [i for i in z.infolist() if not i.is_dir() and i.filename.startswith(prefix)]
        plan = [(i, _safe_target(root, i.filename[len(prefix):])) for i in members]  # tout vérifier d'abord
        for info, target in plan:
            if target is None:
                continue
            data = z.read(info)
            if target.is_file() and target.read_bytes() == data:
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.name in DEFERRED and target.parent == root.resolve():
                target.with_name(target.name + ".new").write_bytes(data)
                deferred.append(target.name)
                continue
            tmp = target.with_name(target.name + ".tmp-maj")
            tmp.write_bytes(data)
            os.replace(tmp, target)
            written += 1
    return {"version": version, "written": written, "deferred": deferred}


RESTART_BAT = r"""@echo off
REM Redemarrage apres une mise a jour (genere par l'application).
cd /d "%~dp0"
ping -n 5 127.0.0.1 >nul
if exist start.bat.new move /y start.bat.new start.bat >nul
if exist restaurer_sauvegarde.bat.new move /y restaurer_sauvegarde.bat.new restaurer_sauvegarde.bat >nul
start "ODDO Sequences" cmd /c start.bat --no-browser
"""


def restart_later(delay: float = 1.5) -> bool:
    """Windows : relance start.bat dans une nouvelle fenêtre puis arrête ce processus.
    Ailleurs (tests, développement) : rien, l'utilisateur relance lui-même."""
    if os.name != "nt" or "pytest" in sys.modules:
        return False
    bat = PROJECT_DIR / "redemarrer.bat"
    bat.write_text(RESTART_BAT.replace("\n", "\r\n"), encoding="ascii")
    flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    subprocess.Popen(["cmd", "/c", str(bat)], cwd=str(PROJECT_DIR), creationflags=flags, close_fds=True)
    threading.Timer(delay, lambda: os._exit(0)).start()
    return True


def install() -> dict:
    from app.backup import backup_now
    from app.db import get_session
    from app.models import EventLog
    with _lock:
        path = updates_dir() / "latest.zip"
        if not path.is_file():
            raise UpdateError("Aucune mise à jour téléchargée : cliquez d'abord sur « Vérifier ».")
        version, _ = inspect(path)
        if parse_version(version) <= parse_version(VERSION):
            raise UpdateError(f"La version {version} n'est pas plus récente que la vôtre ({VERSION}).")
        backup_now("avant-mise-a-jour")
        report = apply_zip(path)
        path.replace(updates_dir() / f"installee-{version}.zip")
        for old in sorted(updates_dir().glob("installee-*.zip"), key=lambda p: p.stat().st_mtime)[:-2]:
            old.unlink(missing_ok=True)
        with get_session() as s:
            s.add(EventLog(level="info", entity="settings",
                           text=f"Mise à jour {VERSION} → {version} installée ({report['written']} fichier(s))"))
            settings_store.set_(s, "update_status", {"checked_at": utcnow().isoformat(), "available": version, "error": None})
            s.commit()
    report["restarting"] = restart_later()
    log.info("Mise à jour %s installée : %s", version, report)
    return report


def check_quietly() -> None:
    try:
        check()
    except Exception:  # noqa: BLE001
        log.exception("Vérification des mises à jour impossible")

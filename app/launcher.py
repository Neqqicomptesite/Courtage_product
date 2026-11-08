"""Point d'entrée lancé par start.bat :  python -m app.launcher

Ordre des opérations :
1. verrou : si l'app tourne déjà, on ouvre juste le navigateur et on s'arrête ;
2. sauvegarde de la base (AVANT les migrations, pour pouvoir revenir en arrière) ;
3. migrations Alembic ;
4. ouverture du navigateur puis démarrage du serveur sur 127.0.0.1:8765.
"""
import logging
import os
import sys
import threading
import webbrowser

import uvicorn

from app import APP_NAME, BASE_URL, HOST, PORT
from app.backup import backup_now
from app.logging_setup import setup_logging
from app.migrate import upgrade_to_head
from app.paths import data_dir, ensure_dirs

log = logging.getLogger("launcher")


class InstanceLock:
    """Verrou exclusif sur data/app.lock, posé par le système d'exploitation.

    Avantage sur un simple « fichier PID » : si l'app plante ou si le PC
    s'éteint, Windows libère le verrou automatiquement. Pas de verrou fantôme.
    """

    def __init__(self, path):
        self.path = path
        self._fh = None

    def acquire(self) -> bool:
        self._fh = open(self.path, "a+")
        try:
            if os.name == "nt":
                import msvcrt
                self._fh.seek(0)
                msvcrt.locking(self._fh.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self._fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self._fh.close()
            self._fh = None
            return False
        return True

    def release(self) -> None:
        if self._fh is not None:
            self._fh.close()  # fermer le fichier libère le verrou
            self._fh = None


def _open_browser_later(delay: float = 1.5) -> None:
    threading.Timer(delay, lambda: webbrowser.open(BASE_URL)).start()


def main() -> int:
    ensure_dirs()
    setup_logging()

    lock = InstanceLock(data_dir() / "app.lock")
    if not lock.acquire():
        print(f"{APP_NAME} est déjà ouvert : ouverture du navigateur.")
        webbrowser.open(BASE_URL)
        return 0

    try:
        backup_now("demarrage")
    except Exception:  # noqa: BLE001 – une sauvegarde ratée ne doit pas empêcher de travailler
        log.exception("Sauvegarde au démarrage impossible")

    log.info("Application des migrations de la base…")
    upgrade_to_head()

    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        busy = probe.connect_ex((HOST, PORT)) == 0
    if busy:
        # Une autre copie (l'ancienne version, ou un autre dossier) occupe déjà l'adresse.
        msg = (f"L'adresse {BASE_URL} est déjà utilisée par une autre copie de {APP_NAME} "
               "(l'ancienne version ?). Fermez sa fenêtre noire, puis relancez start.bat.")
        log.error(msg)
        print("\n  " + msg + "\n")
        lock.release()
        return 1

    print(f"\n  {APP_NAME} tourne sur", BASE_URL)
    print("  Gardez cette fenêtre ouverte : la fermer arrête les envois.\n")
    if "--no-browser" not in sys.argv:
        _open_browser_later()

    from app.web.app import create_app
    uvicorn.run(create_app(), host=HOST, port=PORT, log_level="warning")
    return 0


if __name__ == "__main__":
    sys.exit(main())

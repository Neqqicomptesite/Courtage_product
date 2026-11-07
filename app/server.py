"""V3 : point d'entrée du serveur en ligne :  python -m app.server

Lancé par systemd sur le serveur (voir deploy/). Différences avec app.launcher (poste unique) :
pas de navigateur ni de verrou (systemd garantit une seule copie), pas de sauvegarde SQLite
(la base PostgreSQL est sauvegardée par deploy/backup.sh), écoute derrière Caddy (HTTPS).
"""
import logging
import os
import sys

import uvicorn

from app.logging_setup import setup_logging
from app.migrate import upgrade_to_head
from app.paths import ensure_dirs, is_server_mode

log = logging.getLogger("server")


def main() -> int:
    ensure_dirs()
    setup_logging()
    if not is_server_mode():
        print("DATABASE_URL (PostgreSQL) manquant : ce lanceur est réservé au serveur. Sur un PC : start.bat.")
        return 2
    missing = [k for k in ("SUPABASE_URL", "SUPABASE_PUBLISHABLE_KEY", "ODDO_SECRET_KEY") if not os.environ.get(k)]
    if missing:
        print("Variables manquantes :", ", ".join(missing))
        return 2
    log.info("Application des migrations de la base…")
    upgrade_to_head()
    from app.web.app import create_app
    uvicorn.run(create_app(), host="127.0.0.1", port=int(os.environ.get("ODDO_PORT", "8765")),
                log_level="warning", proxy_headers=True, forwarded_allow_ips="127.0.0.1")
    return 0


if __name__ == "__main__":
    sys.exit(main())

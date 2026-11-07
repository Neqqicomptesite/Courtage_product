"""Emplacements des fichiers. Tout ce qui est propre à l'utilisateur vit dans data/.

La variable d'environnement ODDO_DATA_DIR permet aux tests d'utiliser un
dossier temporaire au lieu de la vraie base.
"""
import os
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
APP_DIR = PROJECT_DIR / "app"
TEMPLATES_DIR = APP_DIR / "templates"
STATIC_DIR = APP_DIR / "static"


def data_dir() -> Path:
    return Path(os.environ.get("ODDO_DATA_DIR", PROJECT_DIR / "data"))


def db_path() -> Path:
    return data_dir() / "oddo.db"


def database_url() -> str:
    """V3 : DATABASE_URL (PostgreSQL du serveur, ex. Supabase) si elle est définie ;
    sinon la base SQLite locale (mode poste unique, comme en V2)."""
    url = os.environ.get("DATABASE_URL", "").strip()
    if url:
        # Supabase donne « postgresql://… » : on précise le pilote psycopg (v3)
        if url.startswith("postgres://"):
            url = "postgresql://" + url[len("postgres://"):]
        if url.startswith("postgresql://"):
            url = "postgresql+psycopg://" + url[len("postgresql://"):]
        return url
    return f"sqlite:///{db_path()}"


def is_server_mode() -> bool:
    """V3 : vrai quand l'appli tourne sur le serveur (PostgreSQL, plusieurs utilisateurs)."""
    return database_url().startswith("postgresql")


def logs_dir() -> Path:
    return data_dir() / "logs"


def backups_dir() -> Path:
    return data_dir() / "backups"


def ensure_dirs() -> None:
    for d in (data_dir(), logs_dir(), backups_dir()):
        d.mkdir(parents=True, exist_ok=True)

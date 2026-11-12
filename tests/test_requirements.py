"""Garde-fou (11/11, panne de la V3.7) : tout paquet importé par l'appli doit être dans requirements.txt,
sinon le serveur (qui n'installe que requirements.txt) ne redémarre pas après une mise à jour."""
import ast
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# nom importé -> paquet de requirements.txt (ou None : apporté par un paquet listé)
PACKAGE = {"fastapi": "fastapi", "uvicorn": "uvicorn", "jinja2": "jinja2", "multipart": "python-multipart",
           "sqlalchemy": "sqlalchemy", "alembic": "alembic", "apscheduler": "apscheduler", "openpyxl": "openpyxl",
           "keyring": "keyring", "psycopg": "psycopg", "jwt": "pyjwt", "cryptography": "cryptography",
           "mammoth": "mammoth", "httpx": "httpx", "xlrd": "xlrd", "tzdata": "tzdata",
           "starlette": None, "pydantic": None, "anyio": None, "typing_extensions": None}
OPTIONAL = {"win32api", "win32con", "win32gui", "pywintypes", "winreg", "msvcrt", "pythoncom", "webview"}


def _imports() -> set[str]:
    names = set()
    for f in (ROOT / "app").rglob("*.py"):
        for node in ast.walk(ast.parse(f.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                names |= {a.name.split(".")[0] for a in node.names}
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                names.add(node.module.split(".")[0])
    return {n for n in names if n != "app" and n not in sys.stdlib_module_names and n not in OPTIONAL}


def test_every_imported_package_is_installed_on_the_server():
    listed = {re.split(r"[\[=<>~ ]", line.strip(), maxsplit=1)[0].lower()
              for line in (ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines()
              if line.strip() and not line.startswith("#")}
    unknown = sorted(n for n in _imports() if n not in PACKAGE)
    assert not unknown, f"Paquets importés à ajouter à requirements.txt (et à PACKAGE ici) : {unknown}"
    missing = sorted(PACKAGE[n] for n in _imports() if PACKAGE[n] and PACKAGE[n] not in listed)
    assert not missing, f"Absents de requirements.txt : {missing}"

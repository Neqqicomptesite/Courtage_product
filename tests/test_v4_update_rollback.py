"""V4 : la mise à jour automatique revient seule à la version d'avant si l'appli ne démarre plus,
et ne réessaie pas la même version fautive (deploy/update.sh, joué dans un faux serveur)."""
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from tests.test_m4_engine import world  # noqa: F401

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "deploy" / "update.sh"
pytestmark = pytest.mark.skipif(shutil.which("bash") is None or shutil.which("git") is None, reason="bash et git requis")


def _git(cwd, *args):
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", *args], cwd=cwd, check=True, capture_output=True)


def _commit(work, state):
    (work / "etat").write_text(state)            # « ok » : l'appli démarre ; « casse » : elle ne répond pas
    _git(work, "add", "-A")
    _git(work, "commit", "--allow-empty", "-qm", state)
    _git(work, "push", "-q", "origin", "HEAD:production")
    return subprocess.run(["git", "rev-parse", "HEAD"], cwd=work, capture_output=True, text=True).stdout.strip()


@pytest.fixture
def server(tmp_path):
    origin, work, app, etc, var, shims = (tmp_path / n for n in ("origin.git", "work", "app", "etc", "var", "bin"))
    for d in (etc, var, shims):
        d.mkdir()
    subprocess.run(["git", "init", "-q", "--bare", str(origin)], check=True)
    subprocess.run(["git", "clone", "-q", str(origin), str(work)], check=True, capture_output=True)
    (work / "requirements.txt").write_text("")
    first = _commit(work, "ok")
    subprocess.run(["git", "clone", "-q", "-b", "production", str(origin), str(app)], check=True, capture_output=True)
    (app / ".venv" / "bin").mkdir(parents=True)
    (app / ".venv" / "bin" / "pip").write_text("#!/bin/sh\nexit 0\n")
    log = tmp_path / "appels.log"
    shim = {  # faux systemctl / curl / journalctl / sauvegarde
        "systemctl": f'#!/bin/sh\necho "systemctl $*" >> {log}\n',
        "journalctl": "#!/bin/sh\necho journal\n",
        "curl": f'#!/bin/sh\nif [ "$(cat {app}/etat)" = ok ]; then printf 200; else printf 000; exit 7; fi\n',
        "backup": f'#!/bin/sh\necho sauvegarde >> {log}\n',
    }
    for name, body in shim.items():
        (shims / name).write_text(body)
    for f in [*shims.iterdir(), app / ".venv" / "bin" / "pip"]:
        f.chmod(0o755)
    (etc / "update-now").write_text("")
    env = {**os.environ, "PATH": f"{shims}:{os.environ['PATH']}", "ODDO_APP": str(app), "ODDO_ETC": str(etc),
           "ODDO_VAR": str(var), "ODDO_BACKUP": str(shims / "backup"), "ODDO_HEALTH_STEP": "0", "ODDO_HEALTH_TRIES": "2"}

    def run():
        (etc / "update-now").write_text("")
        return subprocess.run(["bash", str(SCRIPT)], env=env, capture_output=True, text=True)

    def head():
        return subprocess.run(["git", "rev-parse", "HEAD"], cwd=app, capture_output=True, text=True).stdout.strip()

    return {"work": work, "run": run, "head": head, "first": first, "var": var, "etc": etc, "log": log}


def test_good_update_goes_live(server):
    new = _commit(server["work"], "ok")
    r = server["run"]()
    assert r.returncode == 0, r.stdout + r.stderr
    assert server["head"]() == new and "en ligne" in r.stdout
    assert not (server["var"] / "mise_a_jour_annulee.json").exists()


def test_broken_update_rolls_back_and_is_not_retried(server):
    bad = _commit(server["work"], "casse")
    r = server["run"]()
    assert r.returncode == 0, r.stdout + r.stderr
    assert server["head"]() == server["first"]                     # retour à la version d'avant
    report = json.loads((server["var"] / "mise_a_jour_annulee.json").read_text())
    assert report["refused"] == bad[:7] and report["back_to"] == server["first"][:7] and report["back_ok"] is True
    saves = server["log"].read_text().count("sauvegarde")
    r = server["run"]()                                             # 15 min plus tard : pas de nouvel essai
    assert "déjà refusée" in r.stdout and server["head"]() == server["first"]
    assert server["log"].read_text().count("sauvegarde") == saves   # ni sauvegarde, ni redémarrage inutiles
    fixed = _commit(server["work"], "ok")                           # une version corrigée est essayée
    r = server["run"]()
    assert server["head"]() == fixed and not (server["etc"] / "version-refusee").exists()


def test_admin_is_told_about_the_rollback(client, world, tmp_path, monkeypatch):  # noqa: F811
    from datetime import datetime, timezone

    import app.paths as paths
    from tests.test_m4_engine import world as _w  # noqa: F401
    monkeypatch.setattr(paths, "data_dir", lambda: tmp_path)
    (tmp_path / "mise_a_jour_annulee.json").write_text(json.dumps(
        {"at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "refused": "abc1234", "back_to": "def5678", "back_ok": True}))
    items = client.get("/api/notifications").json()["items"]
    n = next(i for i in items if i["key"] == "rollback:abc1234")
    assert n["title"] == "Mise à jour annulée automatiquement" and "def5678" in n["detail"]

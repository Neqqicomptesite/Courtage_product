import pytest
"""M1 : verrou d'instance unique, sauvegardes, masquage des secrets dans les journaux."""
import logging

from app.backup import KEEP, backup_now
from app.launcher import InstanceLock
from app.logging_setup import RedactingFormatter, redact, register_secret
from app.paths import backups_dir, data_dir, ensure_dirs


def test_second_instance_cannot_take_the_lock():
    ensure_dirs()
    first = InstanceLock(data_dir() / "app.lock")
    second = InstanceLock(data_dir() / "app.lock")
    assert first.acquire() is True
    assert second.acquire() is False


@pytest.mark.sqlite_only
def test_backup_retention(db):
    """V2.20 : les 10 plus récentes + la plus récente de chaque jour sur 30 jours."""
    from datetime import timedelta

    from app.timeutil import to_local, utcnow
    ensure_dirs()
    today = to_local(utcnow()).date()
    for d in range(40):  # 2 sauvegardes par jour sur 40 jours
        day = today - timedelta(days=d + 1)
        for h in ("080000", "180000"):
            (backups_dir() / f"oddo_{day.isoformat()}_{h}_demarrage.db").write_bytes(b"x")
    for i in range(12):  # une journée de redémarrages
        (backups_dir() / f"oddo_{today.isoformat()}_{i:02d}0000_demarrage.db").write_bytes(b"x")
    path = backup_now("test")
    assert path is not None and path.exists()
    names = {p.name for p in backups_dir().glob("oddo_*.db")}
    # V2.23 : la sauvegarde qu'on vient de faire est toujours gardée (même quand, avant 11 h, les
    # fausses sauvegardes « du jour » de ce test paraissent plus récentes qu'elle)
    assert path.name in names and len([n for n in names if n.startswith(f"oddo_{today.isoformat()}")]) == KEEP
    for d in range(1, 30):  # un par jour gardé sur 30 jours, le plus récent du jour
        day = (today - timedelta(days=d)).isoformat()
        assert f"oddo_{day}_180000_demarrage.db" in names and f"oddo_{day}_080000_demarrage.db" not in names
    assert not any(n.startswith(f"oddo_{(today - timedelta(days=35)).isoformat()}") for n in names)
    assert KEEP == 10


def test_secrets_are_redacted():
    register_secret("Sup3r-Secret")
    assert "Sup3r-Secret" not in redact("connexion avec Sup3r-Secret échouée")
    assert redact("AUTH PLAIN AGZvbwBiYXI=") == "AUTH PLAIN ***"
    assert redact('a1 LOGIN o.douiri@oddo.ma "pass"') == "a1 LOGIN ***"

    fmt = RedactingFormatter("%(message)s")
    try:
        raise RuntimeError("le mot de passe Sup3r-Secret est refusé")
    except RuntimeError:
        import sys
        record = logging.LogRecord("t", logging.ERROR, __file__, 1, "erreur", (), sys.exc_info())
    assert "Sup3r-Secret" not in fmt.format(record)  # y compris dans le traceback

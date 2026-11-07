"""Restauration d'une sauvegarde (lancée par restaurer_sauvegarde.bat).

Sécurités :
- refuse de travailler si l'application est ouverte (verrou data/app.lock) ;
- sauvegarde d'abord l'état actuel (« avant_restauration »), pour pouvoir revenir en arrière ;
- copie via l'API « backup » de SQLite : elle gère correctement les fichiers
  oddo.db-wal / oddo.db-shm (une simple copie de fichier pourrait corrompre la base).
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

from app.backup import backup_now
from app.launcher import InstanceLock
from app.paths import backups_dir, data_dir, db_path, ensure_dirs


class RestoreRefused(RuntimeError):
    pass


def list_backups() -> list[Path]:
    return sorted(backups_dir().glob("oddo_*.db"), reverse=True)  # la plus récente d'abord


def restore(source: Path) -> Path | None:
    ensure_dirs()
    lock = InstanceLock(data_dir() / "app.lock")
    if not lock.acquire():
        raise RestoreRefused("L'application est ouverte : fermez-la (fenêtre noire) avant de restaurer.")
    try:
        # 1) Charger la sauvegarde choisie EN MÉMOIRE : la copie de sécurité (étape 2) peut
        #    supprimer la plus ancienne sauvegarde (on n'en garde que 14), peut-être celle-ci.
        #    as_uri() gère les lecteurs Windows (C:) et les espaces dans les chemins.
        src = sqlite3.connect(source.resolve().as_uri() + "?mode=ro", uri=True)
        mem = sqlite3.connect(":memory:")
        try:
            try:
                ok = src.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
            except sqlite3.DatabaseError:
                ok = False
            if not ok:
                raise RestoreRefused(f"La sauvegarde {source.name} est endommagée : choisissez-en une autre.")
            src.backup(mem)
        finally:
            src.close()
        # 2) Sauvegarder l'état actuel, pour pouvoir revenir en arrière.
        safety = backup_now("avant_restauration")
        # 3) Écrire la sauvegarde dans la base (l'API backup gère oddo.db-wal / -shm).
        dest = sqlite3.connect(db_path())
        try:
            mem.backup(dest)
        finally:
            dest.close()
            mem.close()
    finally:
        lock.release()
    return safety


def _describe(p: Path) -> str:
    # oddo_2026-11-03_164554_demarrage.db -> 03/11/2026 16:45:54 (démarrage)
    try:
        _, d, t, *label = p.stem.split("_")
        y, m, j = d.split("-")
        return f"{j}/{m}/{y} {t[:2]}:{t[2:4]}:{t[4:6]}  ({' '.join(label) or 'auto'})"
    except ValueError:
        return p.name


def main() -> int:
    backups = list_backups()
    if not backups:
        print("Aucune sauvegarde trouvée dans data\\backups.")
        return 1
    print("\nSauvegardes disponibles (la plus récente en premier) :\n")
    for i, p in enumerate(backups, start=1):
        print(f"  {i:2d}. {_describe(p)}")
    choice = input("\nNuméro de la sauvegarde à restaurer (Entrée pour annuler) : ").strip()
    if not choice.isdigit() or not 1 <= int(choice) <= len(backups):
        print("Annulé : rien n'a été modifié.")
        return 0
    chosen = backups[int(choice) - 1]
    confirm = input(f"Remplacer les données actuelles par la sauvegarde du {_describe(chosen)} ? Tapez OUI : ")
    if confirm.strip().upper() != "OUI":
        print("Annulé : rien n'a été modifié.")
        return 0
    try:
        safety = restore(chosen)
    except RestoreRefused as exc:
        print(f"\nRestauration impossible : {exc}")
        return 1
    print(f"\nRestauration terminée. L'état précédent a été gardé dans : {safety.name if safety else '—'}")
    print("Vous pouvez relancer start.bat.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

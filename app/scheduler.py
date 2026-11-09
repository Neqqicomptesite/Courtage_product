"""Tâches planifiées, dans le même processus que l'application (§3).

- moteur d'envoi : toutes les minutes ;
- sauvegarde de la base : chaque jour (vérifiée toutes les heures, V2.20), §10 ;
- synchronisation IMAP : déclenchée par le moteur dès que la dernière date de plus
  de 5 minutes (donc toutes les 5 minutes environ, et toujours juste avant un envoi) ;
- récapitulatif quotidien : vérifié chaque minute, part une fois par jour après l'heure choisie.

Rappel : rien ne tourne quand l'application est fermée ou le PC éteint. Au
redémarrage, le moteur rattrape le retard en respectant plafonds et délais.
"""
import logging
from datetime import datetime, timedelta

from apscheduler.schedulers.background import BackgroundScheduler

from app import backup, digest, engine, updater
from app.timeutil import TZ

log = logging.getLogger(__name__)
_scheduler: BackgroundScheduler | None = None


def _safe(fn, name):
    def run():
        try:
            fn()
        except Exception:  # noqa: BLE001 – une tâche qui plante ne doit pas arrêter les suivantes
            log.exception("Tâche « %s » en échec", name)
    return run


def for_each_user(fn):
    """V3 (serveur) : lance `fn` tour à tour pour chaque employé actif qui a une boîte mail,
    en le fixant comme « utilisateur en cours ». En poste unique : un seul appel, comme avant."""
    from app.paths import is_server_mode
    if not is_server_mode():
        return fn

    def run():
        from sqlalchemy import select

        from app.current import as_user
        from app.db import get_session
        from app.models import AppUser, Mailbox
        with get_session() as s:
            people = s.execute(select(AppUser.id, AppUser.role).join(Mailbox, Mailbox.user_id == AppUser.id)
                               .where(AppUser.active.is_(True)).order_by(AppUser.id)).all()
        for uid, role in people:
            try:
                with as_user(uid, role):
                    fn()
            except Exception:  # noqa: BLE001 – un employé en erreur n'empêche pas les autres
                log.exception("Tâche en échec pour l'employé n°%s", uid)
    return run


def start() -> None:
    global _scheduler
    if _scheduler is not None:
        return
    engine.mark_stale_sending(engine.utcnow())  # protection double envoi au démarrage (§6.6)
    sch = BackgroundScheduler(timezone=TZ)
    # max_instances=1 + coalesce : si un passage dure plus d'une minute, on n'en empile pas d'autres.
    sch.add_job(_safe(for_each_user(engine.tick), "moteur d'envoi"), "interval", seconds=60, id="engine", name="moteur d'envoi",
                max_instances=1, coalesce=True)
    sch.add_job(_safe(for_each_user(digest.maybe_send), "récapitulatif"), "interval", seconds=60, id="digest",
                name="récapitulatif quotidien", max_instances=1, coalesce=True)
    from app import quotes  # dossiers de cotation : relances automatiques des compagnies
    sch.add_job(_safe(for_each_user(quotes.run_due_followups), "relances des dossiers"), "interval", seconds=60,
                id="quote_followups", name="relances des dossiers", max_instances=1, coalesce=True)
    from app import contracts  # contrats : tacite reconduction des contrats échus (tout le cabinet)
    sch.add_job(_safe(contracts.run_tacit, "reconduction des contrats"), "interval", hours=6, id="contracts_tacit",
                name="reconduction des contrats", next_run_time=datetime.now(TZ) + timedelta(minutes=3),
                max_instances=1, coalesce=True)
    from app.paths import is_server_mode
    # V2.20 : vérifiée toutes les heures (faite si la dernière a plus de 20 h), même si le PC est éteint le soir.
    # V3 : sur le serveur, la base PostgreSQL est sauvegardée par deploy/backup.sh (systemd).
    if not is_server_mode():
        sch.add_job(_safe(backup.daily_if_due, "sauvegarde"), "interval", hours=1, id="backup",
                    name="sauvegarde quotidienne", next_run_time=datetime.now(TZ) + timedelta(minutes=10),
                    max_instances=1, coalesce=True)
    # V2.17 : nouvelle version ? 2 minutes après le démarrage, puis toutes les 12 heures.
    # (V3 : sur le serveur, les mises à jour arrivent autrement : pas de kit Drive.)
    if not is_server_mode():
        sch.add_job(updater.check_quietly, "interval", hours=12, id="update", name="mises à jour",
                    next_run_time=datetime.now(TZ) + timedelta(minutes=2), max_instances=1, coalesce=True)
    sch.start()
    _scheduler = sch
    log.info("Planificateur démarré (moteur d'envoi chaque minute)")


def stop() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None


def running() -> bool:
    return _scheduler is not None and _scheduler.running

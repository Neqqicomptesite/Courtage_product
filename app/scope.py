"""V3 : chaque employé ne voit que SES campagnes, SES emails, SES rappels, SON journal et les modèles
communs + ses modèles personnels. Les contacts et les entreprises restent communs.

Plutôt que de modifier chacune des ~70 requêtes de l'appli, un filtre global est ajouté
à toute lecture (événement SQLAlchemy « do_orm_execute » + with_loader_criteria). Il ne
s'applique que lorsqu'un employé est « en cours » (app.current) : en poste unique, ou pour
les tâches qui doivent tout voir (anti-doublon entre collègues, administrateur), rien n'est filtré.

Pour lire sans filtre : .execution_options(oddo_all=True) sur la requête.

Dossiers de cotation : les dossiers de cotation (quote_*) sont communs à l'équipe mais propres au cabinet :
ils sont toujours filtrés par org_id (un seul cabinet pour l'instant).
"""
from __future__ import annotations

from sqlalchemy import event, or_, select
from sqlalchemy.orm import ORMExecuteState, Session, with_loader_criteria

from app.current import org_id, user_id

_mailbox_of: dict[int, int] = {}  # employé -> sa boîte (cache ; une boîte ne change pas de propriétaire)


def mailbox_id_of(session: Session, uid: int) -> int:
    """Boîte de l'employé ; -1 s'il n'en a pas encore (il ne voit alors aucun email)."""
    if uid in _mailbox_of:
        return _mailbox_of[uid]
    from app.models import Mailbox
    mbid = session.execute(select(Mailbox.id).where(Mailbox.user_id == uid)
                           .execution_options(oddo_all=True)).scalar()
    if mbid is None:
        return -1
    _mailbox_of[uid] = mbid
    return mbid


def forget_cache() -> None:
    _mailbox_of.clear()


def _apply(state: ORMExecuteState) -> None:
    if not state.is_select or state.execution_options.get("oddo_all"):
        return
    # Dossiers de cotation : tables du cabinet (org_id). Toujours filtrées, employé en cours ou non.
    from app.models import Contract, QuoteCase, QuoteEvent, QuoteFile, QuoteInsurer
    org = org_id()
    state.statement = state.statement.options(*(
        with_loader_criteria(m, lambda t: t.org_id == org, include_aliases=True, track_closure_variables=True)
        for m in (QuoteCase, QuoteInsurer, QuoteEvent, QuoteFile, Contract)))
    uid = user_id()
    if uid is None:
        return
    from app.models import Campaign, Enrollment, EventLog, Message, Reminder, Sequence
    mbid = mailbox_id_of(state.session, uid)
    state.statement = state.statement.options(
        with_loader_criteria(Campaign, lambda c: c.mailbox_id == mbid, include_aliases=True, track_closure_variables=True),
        with_loader_criteria(Enrollment, lambda e: e.campaign_id.in_(
            select(Campaign.id).where(Campaign.mailbox_id == mbid)), include_aliases=True, track_closure_variables=True),
        with_loader_criteria(Message, lambda m: m.mailbox_id == mbid, include_aliases=True, track_closure_variables=True),
        with_loader_criteria(Reminder, lambda r: r.user_id == uid, include_aliases=True, track_closure_variables=True),
        with_loader_criteria(EventLog, lambda ev: ev.user_id == uid, include_aliases=True, track_closure_variables=True),
        with_loader_criteria(Sequence, lambda q: or_(q.owner_id.is_(None), q.owner_id == uid),
                             include_aliases=True, track_closure_variables=True),
    )


def install(session_factory) -> None:
    event.listen(session_factory, "do_orm_execute", _apply)

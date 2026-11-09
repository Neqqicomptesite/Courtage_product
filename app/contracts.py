"""Contrats et échéances.

Un dossier de cotation gagné devient un ou plusieurs contrats (un par branche). Chaque contrat a une
échéance et un préavis de résiliation (60 jours par défaut, réglage du cabinet « contract_notice_days »,
ou la valeur saisie dans le dossier, champ « Préavis de résiliation »). La date limite de préavis
= échéance − préavis. Deux rappels « Renouvellement » sont posés dans l'Agenda du gestionnaire :
2 semaines puis 1 semaine avant cette date limite (choix d'Omar, 09/11).

Renouveler :
- « Lancer le renouvellement » ouvre un dossier de cotation pré-rempli (client, branche, compagnie
  actuelle consultée d'office, prime et taux actuels) ; gagné, il met le contrat à jour, ou le remplace
  si une autre compagnie est retenue ; perdu, il termine le contrat.
- « Renouvelé à l'identique » avance les dates d'un an sur la même ligne (prime ou taux modifiables).
- Tacite reconduction : un contrat échu sans action est reconduit d'un an (tâche quotidienne).
La période précédente est gardée dans `history` (mémoire du cabinet).
"""
from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app import settings_store
from app.current import user_id
from app.models import AppUser, Company, Contact, Contract, QuoteCase, QuoteInsurer, Reminder
from app.timeutil import to_local, utcnow

STATUS_LABELS = {"active": "En cours", "renewing": "Renouvellement en cours", "ended": "Terminé"}
REMINDER_OFFSETS = (14, 7)  # jours avant la date limite de préavis


class ContractError(ValueError):
    def __init__(self, errors: dict):
        super().__init__("; ".join(errors.values()))
        self.errors = errors


def today() -> date:
    return to_local(utcnow()).date()


def add_year(d: date) -> date:
    try:
        return d.replace(year=d.year + 1)
    except ValueError:  # 29 février
        return d.replace(year=d.year + 1, day=28)


def default_end(start: date) -> date:
    return add_year(start) - timedelta(days=1)


def deadline(c: Contract) -> date:
    return c.end_date - timedelta(days=c.notice_days or 0)


def default_notice(s: Session) -> int:
    return int(settings_store.get(s, "contract_notice_days") or 60)


def _log(c: Contract, text: str) -> None:
    c.history = [*(c.history or []), {"ts": utcnow().isoformat(), "text": text}]  # nouvelle liste : JSON modifié


def _date(value, key: str) -> date | None:
    if value in (None, ""):
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        raise ContractError({key: "Date invalide."}) from None


def _amount(value, key: str) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(round(float(str(value).replace(" ", "").replace(" ", "").replace("\xa0", "").replace(",", "."))))
    except ValueError:
        raise ContractError({key: "Montant invalide (chiffres uniquement)."}) from None


def _percent(value, key: str) -> float | None:
    if value in (None, ""):
        return None
    try:
        v = float(str(value).replace("%", "").replace(",", ".").strip())
    except ValueError:
        raise ContractError({key: "Taux invalide (ex. 12,5)."}) from None
    if not 0 <= v <= 100:
        raise ContractError({key: "Taux entre 0 et 100 %."})
    return v


def _int(value, key: str, lo: int, hi: int) -> int | None:
    if value in (None, ""):
        return None
    try:
        v = int(str(value).strip())
    except ValueError:
        raise ContractError({key: "Nombre de jours invalide."}) from None
    if not lo <= v <= hi:
        raise ContractError({key: f"Entre {lo} et {hi} jours."})
    return v


EDITABLE = ("client_name", "company_id", "contact_id", "insurer_id", "insurer_name", "branch", "policy_number",
            "premium", "rate", "commission_rate", "start_date", "end_date", "notice_days", "tacit", "owner_id", "notes")
PLANNING = {"end_date", "notice_days", "owner_id", "client_name", "branch", "insurer_id", "insurer_name"}


def _apply(s: Session, c: Contract, data: dict) -> set[str]:
    """Applique les champs fournis ; renvoie ceux qui ont changé."""
    changed: set[str] = set()
    for k in EDITABLE:
        if k not in data:
            continue
        v = data[k]
        if k in ("start_date", "end_date"):
            v = _date(v, k)
        elif k == "premium":
            v = _amount(v, k)
        elif k == "commission_rate":
            v = _percent(v, k)
        elif k == "notice_days":
            v = _int(v, k, 0, 365)
            v = default_notice(s) if v is None else v
        elif k == "tacit":
            v = bool(v)
        elif k in ("company_id", "contact_id", "insurer_id", "owner_id"):
            v = int(v) if v else None
        elif k == "rate":
            v = str(v or "").strip()[:40] or None
        else:
            v = str(v or "").strip()
            v = v[:{"client_name": 255, "insurer_name": 120, "branch": 40, "policy_number": 60}.get(k, 4000)]
        if getattr(c, k) != v:
            setattr(c, k, v)
            changed.add(k)
    if "insurer_id" in changed and c.insurer_id:
        comp = s.get(Company, c.insurer_id)
        c.insurer_name = comp.name if comp else c.insurer_name
    if "company_id" in changed and c.company_id and not (c.client_name or "").strip():
        comp = s.get(Company, c.company_id)
        c.client_name = comp.name if comp else ""
    if c.start_date and not c.end_date:
        c.end_date = default_end(c.start_date)
        changed.add("end_date")
    errors = {}
    if not (c.client_name or "").strip():
        errors["client_name"] = "Indiquez le client."
    if not (c.branch or "").strip():
        errors["branch"] = "Indiquez la branche."
    if not c.end_date:
        errors["end_date"] = "Indiquez l'échéance (ou la date d'effet)."
    elif c.start_date and c.end_date <= c.start_date:
        errors["end_date"] = "L'échéance doit suivre la date d'effet."
    if not c.insurer_id and not (c.insurer_name or "").strip():
        errors["insurer_id"] = "Indiquez la compagnie."
    if errors:
        raise ContractError(errors)
    return changed


def create(s: Session, data: dict, now_day: date | None = None) -> Contract:
    c = Contract(owner_id=user_id(), notice_days=default_notice(s), history=[], status="active")
    if "company_id" in data and data.get("company_id") and not data.get("client_name"):
        comp = s.get(Company, int(data["company_id"]))
        data = {**data, "client_name": comp.name if comp else ""}
    _apply(s, c, data)
    s.add(c)
    s.flush()
    _log(c, f"Contrat enregistré : {c.insurer_name}, échéance le {c.end_date:%d/%m/%Y}")
    plan_reminders(s, c, now_day)
    return c


def update(s: Session, c: Contract, data: dict, now_day: date | None = None) -> Contract:
    changed = _apply(s, c, data)
    if changed & {"end_date", "notice_days", "premium", "insurer_id", "insurer_name", "start_date"}:
        _log(c, "Modifié : " + ", ".join(sorted(_LABELS.get(k, k) for k in changed)))
    if changed & PLANNING:
        plan_reminders(s, c, now_day)
    return c


_LABELS = {"end_date": "échéance", "notice_days": "préavis", "premium": "prime", "insurer_id": "compagnie",
           "insurer_name": "compagnie", "start_date": "date d'effet"}


# ------------------------------------------------------------------------- rappels de préavis

def close_reminders(s: Session, c: Contract) -> None:
    """Retire les rappels de préavis encore à faire (ceux déjà faits restent dans l'Agenda)."""
    s.execute(delete(Reminder).where(Reminder.contract_id == c.id, Reminder.done_at.is_(None)))


def plan_reminders(s: Session, c: Contract, now_day: date | None = None) -> list[Reminder]:
    """Deux rappels pour le gestionnaire : 2 semaines puis 1 semaine avant la date limite de
    préavis (aujourd'hui si la date est déjà dépassée). Aucun si le préavis est passé."""
    now_day = now_day or today()
    close_reminders(s, c)
    if c.status == "ended":
        return []
    dl = deadline(c)
    if dl < now_day:
        return []
    who = c.owner_id or user_id()
    out = []
    for due in sorted({max(dl - timedelta(days=n), now_day) for n in REMINDER_OFFSETS}):
        r = Reminder(kind="renewal", due_on=due, user_id=who, contract_id=c.id, company_id=c.company_id,
                     contact_id=c.contact_id,
                     title=f"Préavis {c.client_name} · {c.branch} : avant le {dl:%d/%m/%Y}"[:255],
                     notes=(f"Échéance du contrat le {c.end_date:%d/%m/%Y}, préavis {c.notice_days} jours."
                            f" Compagnie : {c.insurer_name or '?'}" + (f", police {c.policy_number}" if c.policy_number else "")
                            + ". Lancez le renouvellement, ou prévenez le client avant cette date."))
        s.add(r)
        out.append(r)
    return out


# ------------------------------------------------------------------------- renouvellement

def renew_same(s: Session, c: Contract, data: dict | None = None, now_day: date | None = None,
               reason: str = "Renouvelé") -> Contract:
    """Nouvelle période sur la même ligne : dates avancées d'un an ; prime, taux, police modifiables."""
    data = data or {}
    old = f"{c.start_date:%d/%m/%Y} → " if c.start_date else ""
    _log(c, f"{reason} : période {old}{c.end_date:%d/%m/%Y}"
         + (f", prime {c.premium:,} MAD".replace(",", " ") if c.premium else "")
         + (f", taux {c.rate}" if c.rate else ""))
    start = _date(data.get("start_date"), "start_date") or (c.end_date + timedelta(days=1))
    end = _date(data.get("end_date"), "end_date") or default_end(start)
    c.start_date, c.end_date = start, end
    _apply(s, c, {k: v for k, v in data.items() if k in ("premium", "rate", "policy_number", "commission_rate",
                                                        "notice_days", "insurer_id", "insurer_name")})
    c.status, c.end_reason, c.renewal_case_id = "active", None, None
    plan_reminders(s, c, now_day)
    return c


def start_renewal(s: Session, c: Contract) -> QuoteCase:
    """Ouvre le dossier de cotation du renouvellement, pré-rempli, compagnie actuelle consultée."""
    from app import quotes
    if c.status == "ended":
        raise ContractError({"status": "Ce contrat est terminé."})
    if c.renewal_case_id and s.get(QuoteCase, c.renewal_case_id):
        raise ContractError({"status": "Un dossier de renouvellement est déjà ouvert."})
    fields = {"date_effet": (c.end_date + timedelta(days=1)).isoformat(), "preavis_jours": str(c.notice_days)}
    case = quotes.create(s, {
        "client_name": c.client_name, "company_id": c.company_id, "contact_id": c.contact_id, "branches": [c.branch],
        "owner_id": c.owner_id, "title": f"Renouvellement {c.branch} – {c.client_name}",
        "current_insurer": c.insurer_name or None, "current_premium": c.premium, "current_rate": c.rate,
        "due_on": deadline(c).isoformat(), "fields": fields})
    if c.insurer_id:
        quotes.add_insurers(s, case, [c.insurer_id], [c.branch], log=False)
    quotes.event(s, case, "note", f"Renouvellement du contrat {c.policy_number or ''} ({c.insurer_name}), "
                                  f"échéance le {c.end_date:%d/%m/%Y}".replace("  ", " "))
    c.renewal_case_id, c.status = case.id, "renewing"
    _log(c, f"Renouvellement lancé : dossier {case.ref}")
    return case


def end(s: Session, c: Contract, reason: str) -> Contract:
    reason = " ".join((reason or "").split())[:255]
    if not reason:
        raise ContractError({"end_reason": "Indiquez le motif (résilié par le client, remplacé…)."})
    c.status, c.end_reason = "ended", reason
    close_reminders(s, c)
    _log(c, f"Terminé : {reason}")
    return c


def renewing_contract(s: Session, case: QuoteCase) -> Contract | None:
    return s.scalars(select(Contract).where(Contract.renewal_case_id == case.id, Contract.status == "renewing")).first()


def on_case_lost(s: Session, case: QuoteCase) -> None:
    """Dossier de renouvellement perdu : le client part, le contrat se termine."""
    c = renewing_contract(s, case)
    if c is not None:
        end(s, c, f"Renouvellement perdu ({case.ref}) : {case.lost_reason or 'sans motif'}")


# ------------------------------------------------------------------------- dossier gagné → contrats

def case_draft(s: Session, case: QuoteCase) -> dict:
    """Pré-remplissage de la fenêtre « Dossier gagné » : une ligne par branche, compagnie retenue
    proposée = la moins chère des offres reçues (sinon la première consultée)."""
    from app import quotes
    old = renewing_contract(s, case)
    fields = case.fields or {}
    start = None
    try:
        start = date.fromisoformat(str(fields.get("date_effet") or "")[:10])
    except ValueError:
        start = None
    if start is None and old is not None:
        start = old.end_date + timedelta(days=1)
    try:
        notice = int(str(fields.get("preavis_jours") or "").strip())
    except ValueError:
        notice = old.notice_days if old else default_notice(s)
    names = {c.id: c.name for c in s.scalars(select(Company).where(Company.kind == "insurer"))}
    rows = list(s.scalars(select(QuoteInsurer).where(QuoteInsurer.case_id == case.id).order_by(QuoteInsurer.id)))
    items = []
    for b in quotes.branches_of(case):
        mine = [r for r in rows if r.branch == b]
        offers = [r for r in mine if r.status in ("offer", "renegotiate")]
        pick = min(offers, key=lambda r: (r.offer_premium is None, r.offer_premium or 0), default=None) or (mine[0] if mine else None)
        items.append({
            "branch": b,
            "choices": [{"company_id": r.company_id, "name": names.get(r.company_id, "?"), "premium": r.offer_premium,
                         "rate": r.offer_rate, "status": r.status} for r in mine],
            "insurer_id": pick.company_id if pick else None,
            "premium": pick.offer_premium if pick else None, "rate": pick.offer_rate if pick else None,
            "policy_number": old.policy_number if old and pick and old.insurer_id == pick.company_id and old.branch == b else "",
            "commission_rate": old.commission_rate if old else None,
            "start_date": start.isoformat() if start else None,
            "end_date": default_end(start).isoformat() if start else None,
            "notice_days": notice,
        })
    return {"items": items, "renewal_of": to_json(s, old) if old else None}


def from_case(s: Session, case: QuoteCase, items: list[dict], now_day: date | None = None) -> list[Contract]:
    """Crée les contrats d'un dossier gagné. Dossier de renouvellement : même compagnie et même
    branche → le contrat existant passe à la période suivante ; sinon il est remplacé."""
    from app import quotes
    old = renewing_contract(s, case)
    made: list[Contract] = []
    kept_old = False
    for it in items:
        b = str(it.get("branch") or "").strip()
        if b not in quotes.branches_of(case):
            raise ContractError({"branch": f"Branche « {b} » absente du dossier."})
        data = {k: it.get(k) for k in ("insurer_id", "insurer_name", "premium", "rate", "policy_number",
                                       "commission_rate", "start_date", "end_date", "notice_days") if k in it}
        if old is not None and not kept_old and old.branch == b and it.get("insurer_id") and int(it["insurer_id"]) == old.insurer_id:
            renew_same(s, old, data, now_day, reason=f"Renouvelé (dossier {case.ref})")
            old.quote_case_id = case.id
            kept_old = True
            made.append(old)
            continue
        c = create(s, {**data, "branch": b, "client_name": case.client_name, "company_id": case.company_id,
                       "contact_id": case.contact_id, "owner_id": case.owner_id}, now_day)
        c.quote_case_id = case.id
        if old is not None and old.branch == b:
            c.previous_id = old.id
        made.append(c)
    if old is not None and not kept_old:
        new = next((c for c in made if c.branch == old.branch), None)
        end(s, old, f"Remplacé : {new.insurer_name} (dossier {case.ref})" if new else f"Non renouvelé (dossier {case.ref})")
    if made:
        quotes.event(s, case, "note", "Contrat(s) enregistré(s) : " + ", ".join(
            f"{c.branch} chez {c.insurer_name}" for c in made))
    return made


# ------------------------------------------------------------------------- tacite reconduction

def roll_tacit(s: Session, now_day: date | None = None) -> int:
    """Contrats « en cours » à tacite reconduction dont l'échéance est passée : période suivante."""
    now_day = now_day or today()
    n = 0
    for c in s.scalars(select(Contract).where(Contract.status == "active", Contract.tacit.is_(True),
                                              Contract.end_date < now_day)).all():
        while c.end_date < now_day:
            renew_same(s, c, None, now_day, reason="Reconduit tacitement")
        n += 1
    return n


def run_tacit() -> None:
    """Tâche planifiée (quotidienne) : pour tout le cabinet, sans employé en cours."""
    from app.db import get_session
    with get_session() as s:
        if roll_tacit(s):
            s.commit()


# ------------------------------------------------------------------------- lecture

def _names(s: Session) -> dict[int, str]:
    return {u.id: u.full_name or u.email for u in s.scalars(select(AppUser))}


def urgency(c: Contract, now_day: date) -> str:
    if c.status == "ended":
        return "ended"
    if c.end_date < now_day:
        return "expired"
    d = (deadline(c) - now_day).days
    return "past_notice" if d < 0 else "urgent" if d <= 14 else "soon" if d <= 60 else "ok"


def to_json(s: Session, c: Contract, names: dict[int, str] | None = None, now_day: date | None = None) -> dict:
    now_day = now_day or today()
    names = names if names is not None else _names(s)
    case = s.get(QuoteCase, c.quote_case_id) if c.quote_case_id else None
    ren = s.get(QuoteCase, c.renewal_case_id) if c.renewal_case_id else None
    contact = s.get(Contact, c.contact_id) if c.contact_id else None
    dl = deadline(c)
    return {
        "id": c.id, "client_name": c.client_name, "company_id": c.company_id,
        "contact": {"id": contact.id, "name": " ".join(x for x in [contact.first_name, contact.last_name] if x) or contact.email}
        if contact else None,
        "insurer_id": c.insurer_id, "insurer_name": c.insurer_name, "branch": c.branch, "policy_number": c.policy_number,
        "premium": c.premium, "rate": c.rate, "commission_rate": c.commission_rate,
        "commission": round(c.premium * c.commission_rate / 100) if c.premium and c.commission_rate is not None else None,
        "start_date": c.start_date.isoformat() if c.start_date else None, "end_date": c.end_date.isoformat(),
        "notice_days": c.notice_days, "deadline": dl.isoformat(), "days_to_deadline": (dl - now_day).days,
        "days_to_end": (c.end_date - now_day).days, "tacit": c.tacit, "status": c.status,
        "status_label": STATUS_LABELS[c.status], "end_reason": c.end_reason, "urgency": urgency(c, now_day),
        "owner": {"id": c.owner_id, "name": names.get(c.owner_id, "")} if c.owner_id else None,
        "quote_case": {"id": case.id, "ref": case.ref} if case else None,
        "renewal_case": {"id": ren.id, "ref": ren.ref, "stage": ren.stage} if ren else None,
        "previous_id": c.previous_id, "notes": c.notes or "", "history": list(reversed(c.history or [])),
    }


FILTERS = {"upcoming": "À renouveler (90 jours)", "active": "En cours", "renewing": "Renouvellement en cours",
           "ended": "Terminés", "all": "Tous"}


def listing(s: Session, flt: str = "upcoming", q: str = "", branch: str = "", owner: str = "",
            company_id: int | None = None, now_day: date | None = None) -> list[Contract]:
    now_day = now_day or today()
    stmt = select(Contract)
    if flt == "upcoming":  # date limite de préavis dans 90 jours ou dépassée (filtrée ci-dessous)
        stmt = stmt.where(Contract.status != "ended", Contract.end_date <= now_day + timedelta(days=90 + 366))
    elif flt == "active":
        stmt = stmt.where(Contract.status != "ended")
    elif flt in ("renewing", "ended"):
        stmt = stmt.where(Contract.status == flt)
    if branch:
        stmt = stmt.where(Contract.branch == branch)
    if owner == "me":
        stmt = stmt.where(Contract.owner_id == user_id())
    elif owner.isdigit():
        stmt = stmt.where(Contract.owner_id == int(owner))
    if company_id:
        stmt = stmt.where(Contract.company_id == company_id)
    if q.strip():
        like = f"%{q.strip()}%"
        stmt = stmt.where(Contract.client_name.ilike(like) | Contract.policy_number.ilike(like)
                          | Contract.insurer_name.ilike(like))
    rows = list(s.scalars(stmt.order_by(Contract.end_date, Contract.id)))
    if flt == "upcoming":
        rows = [c for c in rows if (deadline(c) - now_day).days <= 90]
    return sorted(rows, key=lambda c: (deadline(c), c.id)) if flt != "ended" else rows[::-1]


def summary(s: Session, now_day: date | None = None) -> dict:
    now_day = now_day or today()
    live = list(s.scalars(select(Contract).where(Contract.status != "ended")))
    days = [(deadline(c) - now_day).days for c in live]
    counts = {k: len(s.scalars(select(Contract.id).where(Contract.status == k)).all()) for k in ("renewing", "ended")}
    return {
        "active": len(live), "renewing": counts["renewing"], "ended": counts["ended"],
        "premium": sum(c.premium or 0 for c in live),
        "commission": sum(round((c.premium or 0) * (c.commission_rate or 0) / 100) for c in live),
        "past_notice": sum(1 for c, d in zip(live, days) if d < 0 and c.end_date >= now_day),
        "due_30": sum(1 for d in days if 0 <= d <= 30), "due_60": sum(1 for d in days if 0 <= d <= 60),
        "due_90": sum(1 for d in days if 0 <= d <= 90),
        "upcoming": sum(1 for d in days if d <= 90),
    }


def count_by_company(s: Session) -> dict[int, int]:
    return dict(s.execute(select(Contract.company_id, func.count(Contract.id))
                          .where(Contract.status != "ended", Contract.company_id.is_not(None))
                          .group_by(Contract.company_id)).all())

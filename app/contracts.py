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


# ------------------------------------------------------------------------- réglages par branche
# Par branche : base de calcul de la prime nette (prime = base × taux), taux total des taxes, EVCAT
# (garantie événements catastrophiques, % de la prime nette, plafond éventuel), accessoires et
# commission par défaut. Réglage du cabinet « contract_branches », modifiable dans Réglages.
# Valeurs de départ = tableau d'Omar du 09/11 (« Taxes par branche, prime nette → TTC ») :
#   prime TTC = (prime nette + EVCAT) × (1 + taux total des taxes) + accessoires (non taxés).
# « à compléter » = taux inconnu : la prime TTC n'est pas calculée (DECISIONS 299).
BASES = {"none": "", "payroll": "Masse salariale", "turnover": "Chiffre d'affaires", "capital": "Capitaux assurés",
         "works": "Montant du marché", "value": "Valeur transportée"}
_STD = {"base": "none", "tax_rate": None, "evcat_rate": 0.0, "evcat_cap": None, "accessories": None,
        "commission_rate": None, "per_vehicle": False, "note": "Taux à compléter."}
_MRP = {"base": "capital", "tax_rate": 15.5, "evcat_rate": 8.0, "evcat_cap": 100000,
        "note": "14 % + 1,5 %. EVCAT 8 % de la prime, plafonnée à 100 000 MAD. Accessoires à confirmer."}
_RC = {"base": "turnover", "tax_rate": 15.0, "accessories": 25, "note": "À confirmer sur facture ; EVCAT selon le contrat."}
BRANCH_DEFAULTS = {
    "Flotte": {"tax_rate": 17.0, "evcat_rate": 3.5, "accessories": 17, "per_vehicle": True,
               "note": "Auto RC (offre Wafa) : 14 % + 1,5 % + 1,5 pt non expliqué. EVCAT 3,5 % (2 % transport public "
                       "de voyageurs). Accessoires 17 MAD par véhicule. Garanties annexes : 15,5 %, EVCAT 1,5 %."},
    "Accidents du travail": {"base": "payroll", "tax_rate": 20.0, "accessories": 25,
                             "note": "Confirmé (offre Sanlam : 126 250 net → 151 525 TTC)."},
    "Prévoyance": {"base": "payroll"},
    "Retraite": {"base": "payroll", "note": "Vie : régime à compléter."},
    "RC professionnelle": _RC,
    "RC exploitation": _RC,
    "Multirisque": _MRP,
    "Multirisque habitation": _MRP,
    "Transport": {"base": "value", "note": "Taux à compléter (8,5 % pour les corps de navires seulement)."},
    "Tous risques chantier": {"base": "works"},
    # branches sans fiche de dossier, utiles pour les contrats
    "Auto - garanties annexes": {"tax_rate": 15.5, "evcat_rate": 1.5, "note": "14 % + 1,5 %. EVCAT 1,5 %. Taxes confirmées."},
    "Santé": {"tax_rate": 15.5, "note": "14 % + 1,5 %. À confirmer sur facture."},
    "Assistance": {"tax_rate": 15.5, "note": "14 % + 1,5 %. À confirmer sur facture."},
    "Crédit": {"tax_rate": 15.5, "note": "14 % + 1,5 %. À confirmer sur facture."},
    "Décès emprunteur": {"tax_rate": 11.5, "note": "10 % + 1,5 % ; parafiscale à confirmer."},
    "Corps de navires": {"tax_rate": 8.5, "note": "7 % + 1,5 % ; parafiscale à confirmer."},
}
SETTING_KEYS = ("base", "tax_rate", "evcat_rate", "evcat_cap", "accessories", "commission_rate", "per_vehicle", "note")


def branch_settings(s: Session) -> dict:
    """{branche: {base, base_label, tax_rate, evcat_rate, evcat_cap, accessories, commission_rate,
    per_vehicle, note}} + confirmed (réglages enregistrés par le cabinet, ou valeurs de départ)."""
    from app import quotes
    saved = settings_store.get(s, "contract_branches") or {}
    names = [b["name"] for b in quotes.branches()]
    names += [n for n in BRANCH_DEFAULTS if n not in names]
    names += [n for n in saved.get("items", {}) if n not in names]
    items = {}
    for n in names:
        v = {**_STD, **BRANCH_DEFAULTS.get(n, {}), **(saved.get("items", {}).get(n) or {})}
        v["base_label"] = BASES.get(v["base"], "")
        items[n] = v
    return {"items": items, "confirmed": bool(saved.get("confirmed")), "bases": BASES}


def save_branch_settings(s: Session, items: dict) -> dict:
    current = branch_settings(s)["items"]
    clean = {}
    for name, v in (items or {}).items():
        name = str(name).strip()[:40]
        if not name:
            continue
        base = v.get("base") if v.get("base") in BASES else "none"
        clean[name] = {"base": base,
                       "tax_rate": _percent(v.get("tax_rate"), "tax_rate"),
                       "evcat_rate": _percent(v.get("evcat_rate"), "evcat_rate") or 0.0,
                       "evcat_cap": _amount(v.get("evcat_cap"), "evcat_cap"),
                       "accessories": _amount(v.get("accessories"), "accessories"),
                       "commission_rate": _percent(v.get("commission_rate"), "commission_rate"),
                       "per_vehicle": bool(v.get("per_vehicle", (current.get(name) or {}).get("per_vehicle", False))),
                       "note": " ".join(str(v.get("note") or "").split())[:300]}
    settings_store.set_(s, "contract_branches", {"items": clean, "confirmed": True})
    return branch_settings(s)


def _branch(s: Session, name: str) -> dict:
    return branch_settings(s)["items"].get(name) or {**_STD, "base_label": ""}


def parse_rate(rate: str | None) -> float | None:
    """« 2,1 % » → 0.021 ; « 3 ‰ » → 0.003 ; « 2.1 » → 0.021 (pour cent par défaut)."""
    raw = str(rate or "").strip().replace(",", ".").replace(" ", "").replace("\u202f", "")
    if not raw:
        return None
    per_mille = "‰" in raw
    raw = raw.replace("‰", "").replace("%", "")
    try:
        v = float(raw)
    except ValueError:
        return None
    return v / 1000 if per_mille else v / 100


def amounts(c: Contract) -> dict:
    """Prime TTC = (prime nette + EVCAT) × (1 + taux des taxes) + accessoires (non taxés).
    Taux des taxes inconnu (« à compléter ») : taxes et prime TTC non calculées."""
    net = c.premium
    empty = {"evcat": None, "taxes": None, "ttc": None, "commission": None}
    if net is None:
        return empty
    evcat = round(net * (c.evcat_rate or 0) / 100)
    if c.evcat_cap:
        evcat = min(evcat, c.evcat_cap)
    taxes = round((net + evcat) * c.tax_rate / 100) if c.tax_rate is not None else None
    return {"evcat": evcat, "taxes": taxes,
            "ttc": net + evcat + taxes + (c.accessories or 0) if taxes is not None else None,
            "commission": round(net * c.commission_rate / 100) if c.commission_rate is not None else None}


EDITABLE = ("client_name", "company_id", "contact_id", "insurer_id", "insurer_name", "branch", "policy_number",
            "premium", "rate", "base_amount", "accessories", "tax_rate", "evcat_rate", "evcat_cap", "commission_rate",
            "start_date", "end_date", "notice_days", "tacit", "owner_id", "notes")
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
        elif k in ("premium", "base_amount", "accessories", "evcat_cap"):
            v = _amount(v, k)
        elif k in ("commission_rate", "tax_rate", "evcat_rate"):
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
    # changement de branche : taxes, EVCAT, accessoires et commission de la nouvelle branche,
    # sauf valeurs fournies
    if "branch" in changed or c.id is None:
        cfg = _branch(s, c.branch or "")
        for k in ("tax_rate", "evcat_rate", "evcat_cap", "accessories", "commission_rate"):
            if k not in data or (data.get(k) in (None, "") and c.id is None):
                setattr(c, k, cfg[k])
    # prime nette = base × taux, si la prime n'est pas saisie
    if c.base_amount and parse_rate(c.rate) is not None and ("premium" not in data or data.get("premium") in (None, "")) \
            and changed & {"base_amount", "rate"}:
        c.premium = round(c.base_amount * parse_rate(c.rate))
        changed.add("premium")
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
            "commission_rate": old.commission_rate if old else _branch(s, b)["commission_rate"],
            "base_amount": _base_from_fields(fields, _branch(s, b)["base"]) or (old.base_amount if old else None),
            "accessories": _draft_accessories(_branch(s, b), fields, old),
            "start_date": start.isoformat() if start else None,
            "end_date": default_end(start).isoformat() if start else None,
            "notice_days": notice,
        })
    return {"items": items, "renewal_of": to_json(s, old) if old else None}


def _draft_accessories(cfg: dict, fields: dict, old: Contract | None) -> int | None:
    """Accessoires proposés : ceux du contrat renouvelé, sinon ceux de la branche (Flotte : par véhicule)."""
    if old is not None and old.accessories is not None:
        return old.accessories
    acc = cfg.get("accessories")
    if acc and cfg.get("per_vehicle"):
        try:
            return acc * max(1, int(str(fields.get("nb_vehicules") or "1").strip()))
        except ValueError:
            return acc
    return acc


_BASE_FIELDS = {"payroll": "masse_salariale", "turnover": "ca", "works": "montant_marche", "value": "valeur"}


def _base_from_fields(fields: dict, base: str) -> int | None:
    """Base de calcul reprise de la fiche du dossier (masse salariale, CA, montant du marché…)."""
    key = _BASE_FIELDS.get(base)
    try:
        return _amount(fields.get(key), "base_amount") if key else None
    except ContractError:
        return None


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
        data = {k: it.get(k) for k in ("insurer_id", "insurer_name", "premium", "rate", "policy_number", "base_amount",
                                       "accessories", "commission_rate", "start_date", "end_date", "notice_days") if k in it}
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
        "base_amount": c.base_amount, "base_label": _base_label(s, c.branch), "accessories": c.accessories,
        "tax_rate": c.tax_rate, "evcat_rate": c.evcat_rate, "evcat_cap": c.evcat_cap, **amounts(c),
        "start_date": c.start_date.isoformat() if c.start_date else None, "end_date": c.end_date.isoformat(),
        "notice_days": c.notice_days, "deadline": dl.isoformat(), "days_to_deadline": (dl - now_day).days,
        "days_to_end": (c.end_date - now_day).days, "tacit": c.tacit, "status": c.status,
        "status_label": STATUS_LABELS[c.status], "end_reason": c.end_reason, "urgency": urgency(c, now_day),
        "owner": {"id": c.owner_id, "name": names.get(c.owner_id, "")} if c.owner_id else None,
        "quote_case": {"id": case.id, "ref": case.ref} if case else None,
        "renewal_case": {"id": ren.id, "ref": ren.ref, "stage": ren.stage} if ren else None,
        "previous_id": c.previous_id, "notes": c.notes or "", "history": list(reversed(c.history or [])),
    }


def _base_label(s: Session, branch: str) -> str:
    return _branch(s, branch).get("base_label", "")


FILTERS = {"active": "En cours", "upcoming": "À renouveler (90 jours)", "renewing": "Renouvellement en cours",
           "ended": "Terminés", "all": "Tous"}
SORTS = {"deadline": "Date limite de préavis", "end_date": "Échéance", "client": "Client", "premium": "Prime",
         "insurer": "Compagnie", "recent": "Ajout récent"}


def listing(s: Session, flt: str = "active", q: str = "", branch: str = "", owner: str = "",
            company_id: int | None = None, now_day: date | None = None, *, policy: str = "",
            insurer: str = "", contact_id: int | None = None, end_from: date | None = None,
            end_to: date | None = None, sort: str = "deadline") -> list[Contract]:
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
    if contact_id:
        stmt = stmt.where(Contract.contact_id == contact_id)
    if insurer.isdigit():
        stmt = stmt.where(Contract.insurer_id == int(insurer))
    elif insurer.strip():
        stmt = stmt.where(Contract.insurer_name.ilike(f"%{insurer.strip()}%"))
    if policy.strip():
        stmt = stmt.where(func.replace(Contract.policy_number, " ", "").ilike(f"%{policy.replace(' ', '').strip()}%"))
    if end_from:
        stmt = stmt.where(Contract.end_date >= end_from)
    if end_to:
        stmt = stmt.where(Contract.end_date <= end_to)
    for word in q.split():  # chaque mot doit se trouver dans le client, la police, la compagnie ou la branche
        like = f"%{word}%"
        stmt = stmt.where(Contract.client_name.ilike(like) | Contract.policy_number.ilike(like)
                          | Contract.insurer_name.ilike(like) | Contract.branch.ilike(like))
    rows = list(s.scalars(stmt.order_by(Contract.end_date, Contract.id)))
    if flt == "upcoming":
        rows = [c for c in rows if (deadline(c) - now_day).days <= 90]
    key = {"deadline": lambda c: (deadline(c), c.id), "end_date": lambda c: (c.end_date, c.id),
           "client": lambda c: ((c.client_name or "").lower(), c.id), "premium": lambda c: (-(c.premium or 0), c.id),
           "insurer": lambda c: ((c.insurer_name or "").lower(), c.id), "recent": lambda c: (-c.id,)}
    if flt == "ended" and sort == "deadline":
        return rows[::-1]
    return sorted(rows, key=key.get(sort, key["deadline"]))


def totals(rows: list[Contract]) -> dict:
    """Totaux de la liste affichée (filtres compris)."""
    am = [amounts(c) for c in rows]
    return {"count": len(rows), "premium": sum(c.premium or 0 for c in rows),
            "ttc": sum(a["ttc"] or 0 for a in am), "commission": sum(a["commission"] or 0 for a in am)}


def summary(s: Session, now_day: date | None = None) -> dict:
    now_day = now_day or today()
    live = list(s.scalars(select(Contract).where(Contract.status != "ended")))
    days = [(deadline(c) - now_day).days for c in live]
    counts = {k: len(s.scalars(select(Contract.id).where(Contract.status == k)).all()) for k in ("renewing", "ended")}
    return {
        "active": len(live), "renewing": counts["renewing"], "ended": counts["ended"],
        "premium": sum(c.premium or 0 for c in live),
        "ttc": sum(amounts(c)["ttc"] or 0 for c in live),
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

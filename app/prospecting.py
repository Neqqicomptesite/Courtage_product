"""V3.7 : « Trouver des prospects » avec looot (https://api.looot.ai), réservé à l'administrateur.

Déroulé (validé sur de vrais appels le 11/11/2026) :
1. Aperçu : une page de recherche Prospeo (25 profils, ≈ 0,039 $) avec les filtres du formulaire
   (fonction → intitulés et niveau, secteur → secteurs LinkedIn, ville, taille). On garde cette page :
   elle n'est jamais repayée.
2. Lancement : une tâche de fond (toutes les 20 s, quelques profils à chaque passage) cherche
   l'email pro des profils dont la base dit qu'il est trouvable (job people.email.find, ≈ 0,005 $),
   écarte les personnes déjà connues ou exclues, crée les contacts (codes fonction et secteur
   remplis) et les range dans une liste. Elle s'arrête au nombre voulu, à la fin des résultats,
   sur « Arrêter », ou quand le crédit looot est épuisé (le plafond, c'est le crédit d'Omar).
Chaque appel porte une clé d'idempotence : relancé, il n'est jamais facturé deux fois.
La clé API looot est rangée dans le coffre (comme le mot de passe de la boîte mail), jamais affichée.
"""
from __future__ import annotations

import logging
import math
import re
import unicodedata
from datetime import timedelta

import httpx
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import credentials, suppression
from app.models import AppUser, Contact, ProspectSearch
from app.timeutil import to_local, utcnow

log = logging.getLogger(__name__)

API = "https://api.looot.ai"
KEY_ACCOUNT = "looot-api"            # entrée du coffre
SEARCH_ENDPOINT = "prospeo-search-person"
EMAIL_JOB = "job:people.email.find"
PAGE_SIZE = 25
PAGE_COST = 0.039                    # prix affiché par looot pour une page (11/11/2026)
EMAIL_COST = 0.006                   # moyenne observée (0,005 à 0,009 $)
MAX_PAGES = 40                       # garde-fou : 1 000 profils parcourus au plus par recherche
MAX_WANTED = 500
EMAILS_PER_TICK = 6

# Fonction (code de l'appli) → intitulés recherchés (français et anglais) et niveau dans la base.
FUNCTIONS: dict[str, dict] = {
    "DIR": {"label": "Dirigeant", "titles": [
        "Directeur général", "Directrice générale", "DG", "Gérant", "Gérante", "PDG", "Président", "Fondateur",
        "Co-fondateur", "CEO", "Managing Director", "General Manager", "Founder", "Owner", "Administrateur délégué"]},
    "FIN": {"label": "Finance & administration", "titles": [
        "Directeur financier", "Directrice financière", "DAF", "Directeur administratif et financier",
        "Directrice administrative et financière", "Responsable administratif et financier", "RAF", "CFO",
        "Chief Financial Officer", "Finance Director", "Financial Director", "Head of Finance", "Responsable financier"]},
    "RH": {"label": "RH", "titles": [
        "DRH", "Directeur des ressources humaines", "Directrice des ressources humaines", "Responsable RH",
        "Responsable des ressources humaines", "HR Director", "Head of HR", "Human Resources Director",
        "Chief Human Resources Officer", "HR Manager", "Responsable du personnel"]},
}

# Secteur (code de l'appli) → secteurs de la base (classement LinkedIn). Sert dans les deux sens :
# filtre de recherche, et code secteur du contact importé.
# Valeurs EXACTES de l'énumération Prospeo (prospeo.io/api-docs/enum/industries, 256 valeurs,
# relevée le 11/11/2026) : une valeur hors liste peut faire refuser la recherche.
# Chaque famille (code de séquence) se détaille en industries précises, au choix.
SECTORS: dict[str, dict] = {
    "IND": {"label": "Industrie & énergie", "details": {
        "auto": ("Automobile & équipementiers", ["Motor Vehicle Manufacturing", "Automotive", "Transportation Equipment Manufacturing",
                                                 "Engines and Power Transmission Equipment Manufacturing", "Wholesale Motor Vehicles and Parts"]),
        "aero": ("Aéronautique & défense", ["Aviation and Aerospace Component Manufacturing", "Aviation & Aerospace", "Defense and Space Manufacturing"]),
        "meca": ("Mécanique, machines & métallurgie", ["Industrial Machinery Manufacturing", "Machinery Manufacturing", "Automation Machinery Manufacturing",
                                                        "Mechanical or Industrial Engineering", "Fabricated Metal Products", "Primary Metal Manufacturing",
                                                        "Metal Treatments", "Metalworking Machinery Manufacturing",
                                                        "Agriculture, Construction, Mining Machinery Manufacturing", "HVAC and Refrigeration Equipment Manufacturing"]),
        "elec": ("Électrique & électronique", ["Appliances, Electrical, and Electronics Manufacturing", "Semiconductor Manufacturing",
                                               "Measuring and Control Instrument Manufacturing", "Computer Hardware"]),
        "chimie": ("Chimie, plasturgie & peintures", ["Chemical Manufacturing", "Plastics Manufacturing", "Plastics and Rubber Product Manufacturing",
                                                       "Paint, Coating, and Adhesive Manufacturing", "Personal Care Product Manufacturing", "Cosmetics"]),
        "textile": ("Textile, cuir & habillement", ["Textile Manufacturing", "Apparel Manufacturing", "Leather Product Manufacturing",
                                                     "Fashion Accessories Manufacturing"]),
        "emball": ("Papier, bois & emballage", ["Paper and Forest Products", "Packaging and Containers", "Wood Product Manufacturing",
                                                 "Furniture and Home Furnishings Manufacturing", "Printing Services"]),
        "materiaux": ("Verre, céramique & béton", ["Glass, Ceramics and Concrete Manufacturing"]),
        "mines": ("Mines, pétrole & gaz", ["Oil, Gas, and Mining"]),
        "energie": ("Énergie & renouvelables", ["Renewable Energy", "Electric Power Generation", "Utilities", "Climate Technology Product Manufacturing"]),
        "env": ("Eau, déchets & environnement", ["Environmental Services", "Waste Treatment and Disposal", "Waste Collection",
                                                 "Water Supply and Irrigation Systems", "Water, Waste, Steam, and Air Conditioning Services"]),
        "indus": ("Industrie (autres)", ["General Manufacturing", "Consumer Goods"]),
    }},
    "SRV": {"label": "Services, IT & conseil", "details": {
        "it": ("Informatique & logiciels", ["IT Services and IT Consulting", "Software Development", "Technology, Information and Internet",
                                            "Computer and Network Security", "Data Infrastructure and Analytics", "Information Services"]),
        "telecom": ("Télécoms", ["Telecommunications", "Wireless Services"]),
        "conseil": ("Conseil & services aux entreprises", ["Business Consulting and Services", "Strategic Management Services", "Professional Services",
                                                           "Market Research", "Research Services", "Administrative and Support Services"]),
        "compta": ("Comptabilité, juridique & fiduciaires", ["Accounting", "Legal Services", "Law Practice"]),
        "banque": ("Banque, finance & crédit", ["Banking", "Financial Services", "Investment Management", "Capital Markets", "Credit Intermediation",
                                                "Loan Brokers", "Venture Capital and Private Equity Principals"]),
        "assurance": ("Assurance", ["Insurance", "Claims Adjusting, Actuarial Services"]),
        "rh": ("RH, recrutement & intérim", ["Staffing and Recruiting", "Human Resources Services", "Executive Search Services"]),
        "callcenter": ("Centres d'appels & offshoring", ["Telephone Call Centers"]),
        "pub": ("Communication, médias & publicité", ["Advertising Services", "Marketing Services", "Public Relations and Communications Services",
                                                      "Media Production and Publishing", "Radio and Television Broadcasting"]),
        "formation": ("Enseignement & formation", ["Education Administration Programs", "Higher Education", "Primary and Secondary Education",
                                                   "Professional Training and Coaching", "E-Learning Providers", "Schools"]),
        "tourisme": ("Hôtellerie & tourisme", ["Hospitality", "Accommodation Services", "Travel Arrangements"]),
        "resto": ("Restauration", ["Restaurants", "Food and Beverage Services"]),
        "event": ("Événementiel & loisirs", ["Events Services", "Entertainment Providers", "Recreational Facilities"]),
        "facility": ("Sécurité, nettoyage & services aux bâtiments", ["Security and Investigations", "Facilities Services", "Janitorial Services",
                                                                      "Equipment Rental Services"]),
    }},
    "BTP": {"label": "BTP & immobilier", "details": {
        "construction": ("Construction & travaux", ["Construction", "Civil Engineering", "Specialty Trade Contractors", "Building Structure and Exterior Contractors",
                                                    "Building Finishing Contractors", "Building Equipment Contractors", "Utility System Construction"]),
        "ingenierie": ("Ingénierie & architecture", ["Engineering Services", "Architecture and Planning", "Interior Design", "Surveying and Mapping Services"]),
        "immo": ("Immobilier & promotion", ["Real Estate"]),
        "materiaux": ("Matériaux de construction", ["Building Materials", "Wholesale Building Materials", "Construction Hardware Manufacturing",
                                                     "Retail Building Materials and Garden Equipment"]),
    }},
    "COM": {"label": "Commerce & distribution", "details": {
        "detail": ("Commerce de détail", ["General Retail", "Retail Apparel and Fashion", "Retail Furniture and Home Furnishings", "Retail Office Equipment",
                                          "Retail Health and Personal Care Products", "Retail Pharmacies", "Luxury Goods and Jewelry"]),
        "gms": ("Grande distribution & alimentaire", ["Retail Groceries", "Food and Beverage Retail"]),
        "gros": ("Commerce de gros & négoce", ["General Wholesale", "Wholesale Import and Export", "Wholesale Machinery", "Wholesale Chemical and Allied Products",
                                               "Wholesale Hardware, Plumbing, Heating Equipment", "Wholesale Metals and Minerals",
                                               "Wholesale Computer Equipment", "Wholesale Drugs and Sundries", "International Trade and Development"]),
        "auto": ("Concessionnaires & réparation auto", ["Retail Motor Vehicles", "Vehicle Repair and Maintenance"]),
        "ecom": ("E-commerce", ["Online and Mail Order Retail", "Internet Marketplace Platforms"]),
        "conso": ("Services aux particuliers", ["Consumer Services", "Wellness and Fitness Services"]),
    }},
    "TRA": {"label": "Transport & logistique", "details": {
        "logistique": ("Logistique & entreposage", ["Transportation, Logistics, Supply Chain and Storage", "Warehousing and Storage"]),
        "routier": ("Transport routier", ["Truck and Railroad Transportation", "Freight and Package Transportation", "Ground Passenger Transportation",
                                          "Taxi and Limousine Services"]),
        "maritime": ("Maritime & ports", ["Maritime Transportation", "Maritime", "Shipbuilding"]),
        "aerien": ("Aérien", ["Airlines and Aviation"]),
    }},
    "AGRO": {"label": "Agroalimentaire & agriculture", "details": {
        "agroalim": ("Agroalimentaire", ["Food and Beverage Manufacturing", "Dairy Product Manufacturing", "Wholesale Food and Beverage", "Animal Feed Manufacturing"]),
        "boissons": ("Boissons", ["Wine and Spirits", "Breweries", "Distilleries", "Wineries"]),
        "agri": ("Agriculture, élevage & pêche", ["Farming", "Ranching and Fisheries", "Horticulture"]),
        "tabac": ("Tabac", ["Tobacco Manufacturing"]),
    }},
    "SANTE": {"label": "Santé & pharma", "details": {
        "cliniques": ("Cliniques & hôpitaux", ["Hospitals and Health Care", "Medical Practices", "Mental Health Care", "Home Health Care Services",
                                               "Ambulance Services"]),
        "labos": ("Laboratoires & analyses", ["Medical and Diagnostic Laboratories", "Biotechnology Research"]),
        "pharma": ("Pharmacie & médicament", ["Pharmaceutical Manufacturing", "Wholesale Drugs and Sundries", "Retail Pharmacies"]),
        "materiel": ("Matériel médical", ["Medical Equipment Manufacturing"]),
        "praticiens": ("Dentistes, opticiens & paramédical", ["Dentists", "Optometrists", "Physical, Occupational and Speech Therapists",
                                                              "Veterinary Services"]),
    }},
}
for _s in SECTORS.values():  # toutes les industries d'une famille, sans doublon
    _s["industries"] = list(dict.fromkeys(i for _lbl, inds in _s["details"].values() for i in inds))
# industrie Prospeo → libellé français (affichage et champ « secteur » du contact)
INDUSTRY_FR = {i: lbl for _s in SECTORS.values() for lbl, inds in _s["details"].values() for i in inds}


CITIES = ["Casablanca", "Rabat", "Tanger", "Marrakech", "Agadir", "Fès", "Kénitra", "Mohammedia", "Meknès",
          "Oujda", "El Jadida", "Tétouan", "Salé", "Béni Mellal", "Settat"]
_CITY_EN = {"Tanger": "Tangier", "Fès": "Fes", "Kénitra": "Kenitra", "Meknès": "Meknes", "Tétouan": "Tetouan",
            "Salé": "Sale", "Béni Mellal": "Beni Mellal"}

# Tailles proposées → tranches de la base
SIZES: dict[str, tuple[str, list[str]]] = {
    "tpe": ("1 à 10 salariés", ["1-10"]),
    "pe": ("11 à 50", ["11-20", "21-50"]),
    "pme": ("51 à 200", ["51-100", "101-200"]),
    "eti": ("201 à 1 000", ["201-500", "501-1000"]),
    "ge": ("Plus de 1 000", ["1001-2000", "2001-5000", "5001-10000", "10000+"]),
}


class LoootError(RuntimeError):
    def __init__(self, message: str, code: str = "", status: int | None = None):
        super().__init__(message)
        self.code = code
        self.status = status


class NoCredit(LoootError):
    pass


# --------------------------------------------------------------------------- clé et client

def get_key() -> str | None:
    try:
        return credentials.get_password(KEY_ACCOUNT)
    except credentials.CredentialError:
        return None


def set_key(key: str) -> None:
    credentials.set_password(KEY_ACCOUNT, key.strip())


def delete_key() -> None:
    try:
        credentials.delete_password(KEY_ACCOUNT)
    except credentials.CredentialError:
        pass


class Client:
    """Appels REST à looot. `transport` : pour les tests (httpx.MockTransport)."""

    def __init__(self, key: str, transport=None, base: str = API):
        self._http = httpx.Client(base_url=base, timeout=httpx.Timeout(75.0, connect=10.0), transport=transport,
                                  headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})

    def _check(self, r: httpx.Response) -> dict:
        try:
            data = r.json()
        except ValueError:
            data = {}
        if r.status_code == 402 or (data.get("error") or {}).get("code") == "insufficient_balance":
            raise NoCredit("Crédit looot épuisé : rechargez votre compte looot pour continuer.", "insufficient_balance", r.status_code)
        if r.status_code == 401:
            raise LoootError("Clé API looot refusée : vérifiez-la dans Réglages.", "unauthorized", 401)
        if r.status_code >= 400:
            err = data.get("error") if isinstance(data.get("error"), dict) else {}
            raise LoootError(f"looot a répondu {r.status_code} : {err.get('message') or r.text[:200]}", err.get("code", ""), r.status_code)
        return data

    def balance(self) -> float:
        return float(self._check(self._http.get("/v1/balance")).get("available") or 0)

    def run(self, endpoint: str, inp: dict, key: str, fallback: dict | None = None, wait: int = 40) -> dict:
        body = {"endpointId": endpoint, "input": inp, "idempotencyKey": key}
        if fallback:
            body["fallback"] = fallback
        data = self._check(self._http.post("/v1/runs", params={"wait": wait}, json=body))
        if data.get("status") == "blocked" and (data.get("error") or {}).get("code") == "insufficient_balance":
            raise NoCredit("Crédit looot épuisé : rechargez votre compte looot pour continuer.", "insufficient_balance")
        return data

    def get_run(self, run_id: str) -> dict:
        return self._check(self._http.get(f"/v1/runs/{run_id}"))


def client(transport=None) -> Client:
    key = get_key()
    if not key:
        raise LoootError("Ajoutez d'abord votre clé API looot (Réglages, ou en haut de cette page).", "no_key")
    return Client(key, transport=transport or _TRANSPORT)


_TRANSPORT = None  # remplacé par les tests


# --------------------------------------------------------------------------- critères

def _fold(text: str) -> str:
    return unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode().lower().strip()


def options() -> dict:
    return {"functions": [{"value": k, "label": v["label"]} for k, v in FUNCTIONS.items()],
            "sectors": [{"value": k, "label": v["label"],
                         "details": [{"value": f"{k}.{d}", "label": lbl} for d, (lbl, _i) in v["details"].items()]}
                        for k, v in SECTORS.items()],
            "cities": CITIES, "sizes": [{"value": k, "label": v[0]} for k, v in SIZES.items()],
            "max_wanted": MAX_WANTED, "page_cost": PAGE_COST, "email_cost": EMAIL_COST}


def clean_criteria(raw: dict) -> dict:
    fns = [f for f in raw.get("functions") or [] if f in FUNCTIONS]
    if not fns:
        raise ValueError("Choisissez au moins une fonction.")
    details = [d for d in raw.get("details") or [] if _detail(d)]
    sectors = list(dict.fromkeys([s for s in raw.get("sectors") or [] if s in SECTORS] + [d.split(".")[0] for d in details]))
    return {"functions": fns,
            "sectors": sectors, "details": details,
            "cities": [c for c in raw.get("cities") or [] if c in CITIES],
            "sizes": [z for z in raw.get("sizes") or [] if z in SIZES],
            "wanted": max(1, min(int(raw.get("wanted") or 50), MAX_WANTED))}


def filters(c: dict) -> dict:
    """Critères du formulaire → filtres Prospeo (format vérifié sur de vrais appels)."""
    titles = [t for f in c["functions"] for t in FUNCTIONS[f]["titles"]]
    f: dict = {"person_job_title": {"include": titles}}
    places = [f"{_CITY_EN.get(x, x)}, Morocco" for x in c["cities"]] or ["Morocco"]
    f["person_location_search"] = {"include": places}
    inds = _industries(c)
    if inds:
        f["company_industry"] = {"include": inds}
    if c["sizes"]:
        f["company_headcount_range"] = [r for z in c["sizes"] for r in SIZES[z][1]]
    return f


def _detail(code: str) -> tuple | None:
    fam, _, d = str(code).partition(".")
    return SECTORS.get(fam, {}).get("details", {}).get(d)


def _industries(c: dict) -> list[str]:
    """Une famille sans précision = toutes ses industries ; avec des précisions = seulement celles-là."""
    out: list[str] = []
    details = c.get("details") or []
    for s in c["sectors"]:
        mine = [d for d in details if d.startswith(f"{s}.")]
        out += [i for d in mine for i in _detail(d)[1]] if mine else SECTORS[s]["industries"]
    return list(dict.fromkeys(out))


def describe(c: dict) -> str:
    parts = [" / ".join(FUNCTIONS[f]["label"] for f in c["functions"])]
    if c["sectors"]:
        details = c.get("details") or []
        parts.append(" / ".join(" / ".join(_detail(d)[0] for d in details if d.startswith(f"{s}.")) or SECTORS[s]["label"]
                                for s in c["sectors"]))
    parts.append(", ".join(c["cities"]) if c["cities"] else "tout le Maroc")
    if c["sizes"]:
        parts.append(" / ".join(SIZES[z][0] for z in c["sizes"]))
    return " · ".join(parts)


def _sector_of(industry: str | None, chosen: list[str]) -> str | None:
    if industry:
        for code, s in SECTORS.items():
            if industry in s["industries"]:
                return code
    return chosen[0] if len(chosen) == 1 else None


def _function_of(title: str | None, chosen: list[str]) -> str | None:
    if len(chosen) == 1:
        return chosen[0]
    t = _fold(title or "")
    for code in chosen:
        if any(_fold(x) in t for x in FUNCTIONS[code]["titles"] if len(x) > 3):
            return code
    return None


def _candidate(item: dict) -> dict | None:
    p, co = item.get("person") or {}, item.get("company") or {}
    domain = (co.get("domain") or "").lower().strip()
    email_status = ((p.get("email") or {}).get("status") or "").upper()
    if not domain or not p.get("first_name") or not p.get("last_name"):
        return None
    loc = p.get("location") or {}
    return {"pid": p.get("person_id"), "first": p.get("first_name"), "last": p.get("last_name"),
            "title": p.get("current_job_title"), "company": co.get("name"), "domain": domain,
            "website": co.get("website"), "industry": co.get("industry"),
            "industry_fr": INDUSTRY_FR.get(co.get("industry") or "", co.get("industry")), "size": co.get("employee_range"),
            "city": loc.get("city"), "linkedin": p.get("linkedin_url"), "findable": email_status == "VERIFIED"}


def _cost(run: dict) -> float:
    try:
        return float(run.get("actualCost") or 0)
    except (TypeError, ValueError):
        return 0.0


def fetch_page(cl: Client, ps: ProspectSearch, page: int) -> tuple[list[dict], dict]:
    run = cl.run(SEARCH_ENDPOINT, {"filters": filters(ps.criteria), "page": page},
                 key=f"cotalis-ps{ps.id}-p{page}-{ps.created_at:%Y%m%d%H%M%S}", wait=50)
    ps.cost_usd = round((ps.cost_usd or 0) + _cost(run), 6)
    result = run.get("result") or {}
    items = result.get("results") or []
    return [c for c in (_candidate(i) for i in items) if c], result.get("pagination") or {}


# --------------------------------------------------------------------------- aperçu et lancement

def preview(s: Session, raw: dict, cl: Client | None = None) -> ProspectSearch:
    """Page 1 (≈ 0,039 $), gardée pour la suite : combien de profils, échantillon, coût estimé."""
    from app.current import user_id
    c = clean_criteria(raw)
    ps = ProspectSearch(criteria=c, status="preview", created_by=user_id(), wanted=c["wanted"], state={})
    s.add(ps)
    s.flush()
    cl = cl or client()
    cands, pag = fetch_page(cl, ps, 1)
    ps.total_found = int(pag.get("total_count") or len(cands))
    ps.state = {"page": 2, "total_pages": int(pag.get("total_page") or 1), "queue": cands,
                "seen": [x["pid"] for x in cands if x.get("pid")], "pages": 1}
    return ps


def estimate(ps: ProspectSearch) -> dict:
    st = ps.state or {}
    queue = st.get("queue") or []
    ratio = (sum(1 for x in queue if x.get("findable")) / len(queue)) if queue else 0.0
    wanted = ps.wanted or 0
    hit = 0.85  # part d'emails trouvés parmi les « trouvables » (3 sur 3 lors des essais : prudence)
    per_page = PAGE_SIZE * ratio * hit
    pages = math.ceil(wanted / per_page) if per_page else 0
    reachable = int((ps.total_found or 0) * ratio * hit)
    return {"findable_ratio": round(ratio, 2), "reachable": reachable, "pages": pages,
            "cost_usd": round(max(0, pages - 1) * PAGE_COST + min(wanted, reachable) * EMAIL_COST, 2)}


def start(ps: ProspectSearch, wanted: int | None = None) -> None:
    if ps.status != "preview":
        raise ValueError("Cette recherche est déjà lancée.")
    if wanted:
        ps.wanted = max(1, min(int(wanted), MAX_WANTED))
    ps.status = "running"
    ps.started_at = utcnow()


def stop(ps: ProspectSearch, reason: str = "Arrêtée") -> None:
    if ps.status in ("running", "preview"):
        ps.status = "stopped"
        ps.error = reason
        ps.finished_at = utcnow()


# --------------------------------------------------------------------------- tâche de fond

def _known(s: Session, cand: dict) -> bool:
    """Déjà dans les contacts ? (même prénom et nom, adresse au même domaine)."""
    rows = s.scalars(select(Contact).where(Contact.email.like(f"%@{cand['domain']}")).execution_options(oddo_all=True)).all()
    first, last = _fold(cand["first"]), _fold(cand["last"])
    return any(_fold(r.first_name or "") == first and _fold(r.last_name or "") == last for r in rows)


def _email_of(run: dict) -> str | None:
    if run.get("outcome") != "hit":
        return None
    norm = (run.get("normalized") or {}).get("fields") or {}
    email = norm.get("email")
    if not email:
        res = run.get("result") or {}
        email = res.get("email") or (res.get("data") or {}).get("email")
    email = (email or "").strip().lower()
    return email if re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email) else None


def _ensure_list(s: Session, ps: ProspectSearch):
    from app import lists_service as ls
    from app.models import ContactList
    if ps.list_id and s.get(ContactList, ps.list_id):
        return s.get(ContactList, ps.list_id)
    cl = ls.create(s, f"Recherche · {describe(ps.criteria)} · {to_local(ps.created_at):%d/%m/%Y}"[:120], source="import")
    ps.list_id = cl.id
    return cl


def _import(s: Session, ps: ProspectSearch, cand: dict, email: str) -> bool:
    from app import contacts_service as cs
    from app import lists_service as ls
    from app import vocab
    if s.scalar(select(func.count(Contact.id)).where(Contact.email == email).execution_options(oddo_all=True)):
        ps.skipped_existing = (ps.skipped_existing or 0) + 1
        return False
    if suppression.is_suppressed_db(s, email):
        ps.skipped_excluded = (ps.skipped_excluded or 0) + 1
        return False
    c = ps.criteria
    fn, sec = _function_of(cand.get("title"), c["functions"]), _sector_of(cand.get("industry"), c["sectors"])
    data = {"email": email, "first_name": cand["first"], "last_name": cand["last"], "company": cand.get("company"),
            "job_title": cand.get("title"), "sector": cand.get("industry_fr") or cand.get("industry"), "kind": "prospect",
            "target_segment": vocab.TARGETS.get(fn) if fn else None,
            "sector_family": vocab.SECTORS.get(sec) if sec else None,
            "website": cand.get("website") or f"https://{cand['domain']}", "linkedin_url": cand.get("linkedin"),
            "size_bucket": cand.get("size"), "email_reliability": "Bonne"}
    try:
        contact, _ = cs.create_contact(s, {k: v for k, v in data.items() if v}, f"Recherche looot du {to_local(ps.created_at):%d/%m/%Y}")
    except cs.ContactInvalid:  # adresse refusée par nos règles : comptée comme « sans email utilisable »
        ps.skipped_no_email = (ps.skipped_no_email or 0) + 1
        return False
    if fn and sec and not contact.sequence_code:
        contact.sequence_code = vocab.sequence_code(fn, sec)
    if cand.get("city"):
        contact.custom = {**(contact.custom or {}), "ville": cand["city"]}
    lst = _ensure_list(s, ps)
    ls.add(s, lst, [contact.id])
    ls.stamp_lot(s, lst, [contact.id])  # V3.7 : chaque recherche est un lot numéroté (variante n des textes)
    ps.imported = (ps.imported or 0) + 1
    return True


def work(s: Session, ps: ProspectSearch, cl: Client, budget: int = EMAILS_PER_TICK) -> None:
    """Un passage : quelques recherches d'email, ou une page de plus quand la file est vide."""
    st = dict(ps.state or {})
    queue = list(st.get("queue") or [])
    try:
        while budget > 0 and ps.status == "running":
            if (ps.imported or 0) >= ps.wanted:
                ps.status, ps.finished_at = "done", utcnow()
                break
            if not queue:
                page, total = st.get("page", 1), st.get("total_pages", 1)
                if page > total or st.get("pages", 0) >= MAX_PAGES:
                    ps.status, ps.finished_at = "done", utcnow()
                    ps.error = None if (ps.imported or 0) else "Plus de profils correspondants"
                    break
                cands, pag = fetch_page(cl, ps, page)
                seen = set(st.get("seen") or [])
                queue = [x for x in cands if x.get("pid") not in seen]
                st.update(page=page + 1, total_pages=int(pag.get("total_page") or total),
                          seen=list(seen | {x["pid"] for x in cands if x.get("pid")}), pages=st.get("pages", 0) + 1)
                budget -= 1
                continue
            cand = queue.pop(0)
            ps.checked = (ps.checked or 0) + 1
            if not cand.get("findable"):
                ps.skipped_no_email = (ps.skipped_no_email or 0) + 1
                continue
            if _known(s, cand):
                ps.skipped_existing = (ps.skipped_existing or 0) + 1
                continue
            run = cl.run(EMAIL_JOB, {"first_name": cand["first"], "last_name": cand["last"], "domain": cand["domain"]},
                         key=f"cotalis-ps{ps.id}-e-{cand.get('pid') or cand['first'] + cand['last'] + cand['domain']}",
                         fallback={"enabled": True, "maxCostUsd": 0.03, "maxAttempts": 3}, wait=40)
            ps.cost_usd = round((ps.cost_usd or 0) + _cost(run), 6)
            budget -= 1
            email = _email_of(run)
            if not email:
                ps.skipped_no_email = (ps.skipped_no_email or 0) + 1
                continue
            ps.emails_found = (ps.emails_found or 0) + 1
            _import(s, ps, cand, email)
    except NoCredit as exc:
        ps.status, ps.error, ps.finished_at = "stopped", str(exc), utcnow()
    except (LoootError, httpx.HTTPError) as exc:
        ps.failures = (ps.failures or 0) + 1
        ps.error = f"Problème passager avec looot : {exc}"
        if ps.failures >= 5:
            ps.status, ps.finished_at = "failed", utcnow()
            ps.error = f"Arrêtée après plusieurs erreurs de looot : {exc}"
    st["queue"] = queue
    ps.state = st


def tick(transport=None) -> int:
    """Tâche de fond (toutes les 20 s) : fait avancer les recherches lancées."""
    from app.current import as_user
    from app.db import get_session
    n = 0
    with get_session() as s:
        ids = list(s.scalars(select(ProspectSearch.id).where(ProspectSearch.status == "running")
                             .order_by(ProspectSearch.id).execution_options(oddo_all=True)))
    for pid in ids:
        with get_session() as s:
            ps = s.get(ProspectSearch, pid)
            user = s.get(AppUser, ps.created_by) if ps.created_by else None
            try:
                cl = client(transport)
            except LoootError as exc:
                ps.status, ps.error, ps.finished_at = "stopped", str(exc), utcnow()
                s.commit()
                continue
            with as_user(user.id if user else None, user.role if user else "admin"):
                work(s, ps, cl)
            ps.updated_at = utcnow()
            s.commit()
            n += 1
    return n


def to_json(ps: ProspectSearch, sample: bool = False) -> dict:
    out = {"id": ps.id, "status": ps.status, "criteria": ps.criteria, "summary": describe(ps.criteria),
           "wanted": ps.wanted, "total_found": ps.total_found, "checked": ps.checked or 0,
           "emails_found": ps.emails_found or 0, "imported": ps.imported or 0,
           "skipped_existing": ps.skipped_existing or 0, "skipped_no_email": ps.skipped_no_email or 0,
           "skipped_excluded": ps.skipped_excluded or 0, "cost_usd": round(ps.cost_usd or 0, 3),
           "list_id": ps.list_id, "error": ps.error,
           "created_at": ps.created_at.isoformat() if ps.created_at else None,
           "finished_at": ps.finished_at.isoformat() if ps.finished_at else None}
    if ps.status == "preview":
        out["estimate"] = estimate(ps)
    if sample:
        out["sample"] = [{**{k: x.get(k) for k in ("first", "last", "title", "company", "size", "city", "findable")},
                          "industry": x.get("industry_fr") or x.get("industry")}
                         for x in (ps.state or {}).get("queue", [])[:10]]
    return out


def purge_old_previews(s: Session) -> None:
    """Aperçus jamais lancés de plus de 7 jours : on les retire (rien n'a été importé)."""
    for ps in s.scalars(select(ProspectSearch).where(ProspectSearch.status == "preview",
                                                     ProspectSearch.created_at < utcnow() - timedelta(days=7))):
        s.delete(ps)

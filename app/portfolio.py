"""V3.10 : portefeuille clients (export DIAMM) : import, consolidation, analyse, vente croisée.

- Import : l'export DIAMM tel quel (.xls, .xlsx ou .csv), une ligne par police. Les colonnes sont
  reconnues par leur nom (CLIENT, Particulier, TELEP1, AEMAIL, POLICE, COMPAGNIE, BRANCHE…). Les
  colonnes inconnues sont gardées dans « raw ». Primes et échéances sont prises si elles existent.
- Consolidation : un client par nom (normalisé), toutes ses polices rattachées. Clé d'une police :
  compagnie + n° de police. Réimporter met à jour, sans doublon.
- Segment : colonne « Particulier » (O = particulier, N = entreprise).
- Familles : les ~50 branches DIAMM regroupées en familles (Auto, Habitation…) pour la vente croisée.
- Contacts : un client avec email devient (ou reste) un contact « client » de l'appli, pour les
  campagnes ; un prospect déjà présent avec cette adresse passe « client » (ses prospections s'arrêtent).
- Commun à l'équipe du cabinet (org_id) ; l'import est réservé à l'administrateur (côté API).
"""
from __future__ import annotations

import csv
import io
import re
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import CALL_OUTCOMES, Contact, PortfolioAmendment, PortfolioCall, PortfolioClient, PortfolioContract
from app.timeutil import utcnow

SOURCE = "Portefeuille DIAMM"
MAX_FILE = 30 * 1024 * 1024

# ------------------------------------------------------------------ familles

FAMILIES: dict[str, str] = {
    "AUTO PARTICULIERS": "Auto", "AUTO CYCLO": "Auto", "CARTE VERTE AUTO": "Auto",
    "AUTO FLOTTE": "Flotte auto", "P.T.A FLOTTE": "Flotte auto",
    "MULTIRISQUE HABITATIONS": "Habitation", "MULTIRISQUE HABITATION": "Habitation",
    "D.I.M": "Santé / prévoyance", "ALLIANZ CHIFAA": "Santé / prévoyance", "ASSUR SANTE INTERNATIONAL": "Santé / prévoyance",
    "DYNAMIC SANTE INTERNATIONAL.": "Santé / prévoyance", "SEHASSUR": "Santé / prévoyance", "SEHHA OPTIMAL PLUS": "Santé / prévoyance",
    "VITALIS": "Santé / prévoyance", "ASSISTANCE SANTE": "Santé / prévoyance",
    "PRE-RETRAITES": "Retraite", "RETRAITE COMPLEMENTAIRE": "Retraite",
    "INDIVIDUELLE ACCIDENT": "Individuelle accident",
    "ASSISTANCE DE VOYAGE": "Assistance voyage", "INJAD MONDE": "Assistance voyage",
    "ASSISTANCE AUTO": "Assistance auto",
    "ASSISTANCE SCOLAIRE": "Scolaire", "VITAL ASSISTANCE SCOLAIRE": "Scolaire", "RC SCOLAIRE": "Scolaire",
    "ACCIDENTS DE TRAVAIL": "Accidents du travail", "ACCIDENTS DU TRAVAIL": "Accidents du travail",
    "RC. EXPLOITATION": "RC entreprise", "RC. EXPLOIT. & PROFES.": "RC entreprise", "RC. EXPLOIT.& PRODUITS": "RC entreprise",
    "RC. PRODUITS": "RC entreprise", "RC. PROFESSIONNELLE": "RC entreprise", "CYBEREDGE": "RC entreprise",
    "RC COLONNIE DE VACANCES": "RC entreprise", "RC GARDIENNES": "RC entreprise", "RC SPORT": "RC entreprise",
    "MULTIRISQUE BUREAUX": "Multirisque pro", "MULTIRISQUE COMMERCE": "Multirisque pro", "MULTIRISQUE PROFESSIONNELLE": "Multirisque pro",
    "MULTIRISQUE INDUSTRIELLE": "Multirisque pro", "MULTIRISQUE HOTEL": "Multirisque pro", "MULTIRISQUE IMMEUBLE": "Multirisque pro",
    "INCENDIE / EXPLOSION": "Multirisque pro", "VOL.": "Multirisque pro", "B.D.M.": "Multirisque pro",
    "T.R.C.": "Construction", "RC DECENNALE": "Construction", "T.R.M": "Construction",
    "FACULTES MARITIME R.O.": "Transport marchandises", "FACULTES MARITIME R.G": "Transport marchandises",
    "MARCHANDISES TRANSPORTEES": "Transport marchandises", "TRANSPORT AIR": "Transport marchandises", "TRANSPORT TERRE": "Transport marchandises",
    "CORPS DE PECHE": "Bateaux", "CORPS DE PLAISANCE": "Bateaux",
    "ASSURANCE CREDIT": "Assurance crédit",
}
# Catégorie DIAMM -> famille, pour une branche inconnue
CATEGORY_FAMILIES: dict[str, str] = {
    "AUTOMOBILE": "Auto", "CARTE VERTE AUTO": "Auto", "ACCIDENTS DU TRAVAIL": "Accidents du travail",
    "PREVOYANCE": "Santé / prévoyance", "INDIVIDUELLE ACCIDENT": "Individuelle accident", "INCENDIE": "Multirisque pro",
    "RESPONSABILITES CIVILES": "RC entreprise", "MARITIME FACULTES": "Transport marchandises", "MARITIME CORPS": "Bateaux",
    "RETRAITE COMPLEMENTAIRE": "Retraite", "ASSISTANCE": "Assistance voyage", "RISQUES DIVERS": "Autres risques",
}
# Familles qui ont un sens pour chaque segment (pour « ce qui lui manque »)
RELEVANT = {
    "particulier": ["Auto", "Habitation", "Santé / prévoyance", "Assistance auto", "Assistance voyage", "Individuelle accident",
                    "Retraite", "Scolaire"],
    "pro": ["Accidents du travail", "Santé / prévoyance", "RC entreprise", "Multirisque pro", "Flotte auto", "Auto",
            "Transport marchandises", "Construction", "Retraite", "Assistance voyage"],
}


def family_of(branch: str, category: str = "") -> str:
    b, c = _up(branch), _up(category)
    if b in FAMILIES:
        return FAMILIES[b]
    if "FLOTTE" in b:
        return "Flotte auto"
    if "HABITATION" in b:
        return "Habitation"
    if b.startswith("RC") or "RESPONSABILITE" in b:
        return "RC entreprise"
    if "MULTIRISQUE" in b:
        return "Multirisque pro"
    if "SANTE" in b or "MALADIE" in b:
        return "Santé / prévoyance"
    return CATEGORY_FAMILIES.get(c, (category or branch or "Autre").strip().capitalize())


# ------------------------------------------------------------------ opportunités (vente croisée)

@dataclass(frozen=True)
class Rule:
    key: str
    label: str
    pitch: str
    segment: str | None          # particulier, pro ou None (tous)
    has: tuple[str, ...] = ()    # au moins une de ces familles
    lacks: tuple[str, ...] = ()  # aucune de ces familles
    mono: bool = False           # un seul produit chez nous


RULES: list[Rule] = [
    Rule("part-auto-habitation", "Auto, sans Habitation", "Proposer la multirisque habitation", "particulier", ("Auto",), ("Habitation",)),
    Rule("part-sante", "Sans santé / prévoyance", "Proposer une complémentaire santé", "particulier", (), ("Santé / prévoyance",)),
    Rule("part-auto-assistance", "Auto, sans Assistance auto", "Proposer l'assistance auto", "particulier", ("Auto",), ("Assistance auto",)),
    Rule("part-habitation-auto", "Habitation, sans Auto", "Mettre en concurrence son assurance auto", "particulier", ("Habitation",), ("Auto",)),
    Rule("part-ia", "Sans Individuelle accident", "Proposer l'individuelle accident", "particulier", (), ("Individuelle accident",)),
    Rule("part-mono", "Un seul produit chez le cabinet", "Faire le point sur toutes ses assurances", "particulier", mono=True),
    Rule("pro-rc", "Sans RC entreprise", "Proposer la RC exploitation / professionnelle", "pro", (), ("RC entreprise",)),
    Rule("pro-multirisque", "Sans Multirisque pro", "Proposer la multirisque (locaux, matériel, marchandises)", "pro", (), ("Multirisque pro",)),
    Rule("pro-at-sante", "Accidents du travail, sans santé de groupe", "Proposer la santé / prévoyance de groupe", "pro",
         ("Accidents du travail",), ("Santé / prévoyance",)),
    Rule("pro-auto-at", "Auto ou flotte, sans Accidents du travail", "Mettre en concurrence les accidents du travail", "pro",
         ("Auto", "Flotte auto"), ("Accidents du travail",)),
    Rule("pro-sante-at", "Santé de groupe, sans Accidents du travail", "Mettre en concurrence les accidents du travail", "pro",
         ("Santé / prévoyance",), ("Accidents du travail",)),
    Rule("pro-transport-flotte", "Transport de marchandises, sans flotte", "Proposer l'assurance de leurs véhicules", "pro",
         ("Transport marchandises",), ("Flotte auto", "Auto")),
    Rule("pro-mono", "Un seul produit chez le cabinet", "Faire le point sur toutes les assurances de l'entreprise", "pro", mono=True),
]


def rule_matches(r: Rule, segment: str, fams: set[str]) -> bool:
    if r.segment and r.segment != segment or not fams:
        return False
    if r.mono:
        return len(fams) == 1
    if r.has and not fams.intersection(r.has):
        return False
    return not fams.intersection(r.lacks)


# ------------------------------------------------------------------ lecture du fichier

COLUMNS: dict[str, tuple[str, ...]] = {
    "client": ("CLIENT", "NOMCLIENT", "ASSURE", "SOUSCRIPTEUR", "RAISONSOCIALE", "NOM"),
    "particulier": ("PARTICULIER",),
    "tel1": ("TELEP1", "TEL1", "TELEPHONE", "TEL", "GSM", "MOBILE"),
    "tel2": ("TELEP2", "TEL2", "TELEPHONE2"),
    "fax": ("FAX",),
    "note": ("RESPONSABLE", "CONTACT", "INTERLOCUTEUR"),
    "email": ("AEMAIL", "EMAIL", "MAIL", "ADRESSEEMAIL", "COURRIEL"),
    "policy": ("POLICE", "NPOLICE", "NUMPOLICE", "NUMEROPOLICE", "NOPOLICE"),
    "insurer": ("COMPAGNIE", "ASSUREUR", "CIE"),
    "category": ("CATEGORIE",),
    "branch": ("BRANCHE", "PRODUIT"),
    "fixed": ("FERMERENO", "FERME"),
    "cancelled_on": ("DATERESI", "DATERESILIATION"),
    "cancelled": ("RESILIEE", "RESILIE", "RESILIATION"),
    "fleet": ("FLOTTE",),
    "premium": ("PRIME", "PRIMETTC", "PRIMETOTALE", "PRIMENETTE", "PTTC", "MONTANTPRIME", "PRIMEANNUELLE"),
    "due": ("ECHEANCE", "DATEECHEANCE", "DATEECH", "ECHEANCEPRINCIPALE", "PROCHAINEECHEANCE"),
    # V3.13 : lus si l'export DIAMM les contient (l'export actuel n'a pas ces colonnes)
    "start": ("DATEEFFET", "DATEDEFFET", "EFFET", "DATEDEBUT"),
    "subscribed": ("DATESOUSCRIPTION", "DATESOUS", "SOUSCRIPTION", "DATEEMISSION"),
    "aperiteur": ("NAPERITEUR", "NUMAPERITEUR", "NUMEROAPERITEUR", "NOAPERITEUR", "POLICEAPERITEUR", "APERITEUR"),
    "coinsurance": ("COASSURANCE", "COASS", "COASSURE"),
    "last_claim": ("DATEDERNIERSINISTRE", "DERNIERSINISTRE", "DATESINISTRE"),
}
REQUIRED = ("client", "policy", "insurer")


class PortfolioError(ValueError):
    pass


def _up(s) -> str:
    return " ".join(str(s or "").upper().split())


def _hkey(h) -> str:
    t = unicodedata.normalize("NFKD", str(h or "")).encode("ascii", "ignore").decode().upper()
    return re.sub(r"[^A-Z0-9]", "", t)


def client_key(name: str) -> str:
    t = unicodedata.normalize("NFKD", str(name or "")).encode("ascii", "ignore").decode().upper()
    return " ".join(re.sub(r"[^A-Z0-9]+", " ", t).split())


def read_rows(path: Path) -> tuple[list[str], list[list]]:
    """En-têtes et lignes (valeurs Python ; dates en date). .xls (xlrd), .xlsx (openpyxl), .csv."""
    ext = path.suffix.lower()
    if ext == ".xls":
        import xlrd
        try:
            wb = xlrd.open_workbook(str(path))
        except Exception as exc:  # noqa: BLE001
            raise PortfolioError(f"Fichier .xls illisible ({exc}).") from None
        sh = max(wb.sheets(), key=lambda x: x.nrows)
        out = []
        for r in range(sh.nrows):
            row = []
            for c in range(sh.ncols):
                cell = sh.cell(r, c)
                if cell.ctype == xlrd.XL_CELL_DATE:
                    try:
                        row.append(xlrd.xldate_as_datetime(cell.value, wb.datemode).date())
                    except Exception:  # noqa: BLE001
                        row.append(cell.value)
                else:
                    row.append(cell.value)
            out.append(row)
    elif ext in (".xlsx", ".xlsm"):
        import openpyxl
        wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
        ws = max(wb.worksheets, key=lambda w: w.max_row or 0)
        out = [[v.date() if isinstance(v, datetime) else v for v in r] for r in ws.iter_rows(values_only=True)]
        wb.close()
    elif ext == ".csv":
        data = path.read_bytes()
        for enc in ("utf-8-sig", "cp1252"):
            try:
                text = data.decode(enc)
                break
            except UnicodeDecodeError:
                continue
        delim = ";" if text[:3000].count(";") > text[:3000].count(",") else ","
        out = list(csv.reader(io.StringIO(text), delimiter=delim))
    else:
        raise PortfolioError("Format non pris en charge : choisissez l'export DIAMM en .xls, .xlsx ou .csv.")
    out = [r for r in out if any(str(v).strip() for v in r if v is not None)]
    if not out:
        raise PortfolioError("Le fichier est vide.")
    # ligne d'en-tête : la première (parmi les 10 premières) qui contient CLIENT et POLICE
    for i, r in enumerate(out[:10]):
        keys = {_hkey(v) for v in r}
        if keys & set(COLUMNS["client"]) and keys & set(COLUMNS["policy"]):
            return [str(v or "").strip() for v in r], out[i + 1:]
    return [str(v or "").strip() for v in out[0]], out[1:]


def map_columns(headers: list[str]) -> dict[str, int]:
    found: dict[str, int] = {}
    keys = [_hkey(h) for h in headers]
    for fld, aliases in COLUMNS.items():
        for alias in aliases:  # l'ordre des alias compte (TELEPHONE avant TEL…)
            if alias in keys and keys.index(alias) not in found.values():
                found[fld] = keys.index(alias)
                break
    missing = [f for f in REQUIRED if f not in found]
    if missing or ("branch" not in found and "category" not in found):
        names = {"client": "CLIENT", "policy": "POLICE", "insurer": "COMPAGNIE"}
        need = [names[m] for m in missing] + ([] if "branch" in found or "category" in found else ["BRANCHE"])
        raise PortfolioError(f"Colonnes introuvables : {', '.join(need)}. Est-ce bien l'export du portefeuille DIAMM ?")
    return found


def _text(v) -> str:
    if v is None:
        return ""
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    return " ".join(str(v).split())


def _yes(v) -> bool:
    return _up(v) in ("O", "OUI", "Y", "YES", "1", "X", "VRAI", "TRUE")


def _date(v) -> date | None:
    if isinstance(v, date):
        return v
    if isinstance(v, (int, float)) and 20000 < v < 80000:  # numéro de série Excel
        return date(1899, 12, 30) + timedelta(days=int(v))
    s = _text(v)
    if re.fullmatch(r"\d{5}(\.0+)?", s) and 20000 < float(s) < 80000:  # numéro de série Excel, en texte (CSV)
        return date(1899, 12, 30) + timedelta(days=int(float(s)))
    for fmt in ("%d/%m/%Y", "%d/%m/%y", "%Y-%m-%d", "%d-%m-%Y", "%d.%m.%Y"):
        try:
            return datetime.strptime(s[:10], fmt).date()
        except ValueError:
            continue
    return None


def _amount(v) -> float | None:
    if isinstance(v, (int, float)):
        return float(v)
    s = re.sub(r"[^\d,.\-]", "", _text(v))
    if not s:
        return None
    if "," in s and "." in s:
        s = s.replace(".", "").replace(",", ".") if s.rfind(",") > s.rfind(".") else s.replace(",", "")
    else:
        s = s.replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


EMAIL_FIND = re.compile(r"[a-z0-9._%+'-]+@[a-z0-9.-]+\.[a-z]{2,}")


def first_email(v) -> str | None:
    m = EMAIL_FIND.search(_text(v).lower())
    return m.group(0) if m else None


PHONE_RE = re.compile(r"\+?\d[\d .\-]{7,}\d")


def phones_of(*values) -> list[dict]:
    """« 0674904197- LEILA » ou « LEILA / 0674904197 » -> {"number": "0674904197", "label": "Leila"}.
    Le texte autour du numéro devient son libellé (la personne, « bureau »…)."""
    out, seen = [], set()
    for v in values:
        s = _text(v)
        if not s:
            continue
        for part in re.split(r"\s*(?:;|\||\bET\b)\s*", s, flags=re.I):
            nums = PHONE_RE.findall(part)
            label = PHONE_RE.sub(" ", part)
            label = re.sub(r"^[\s\-:,/.]+|[\s\-:,/.]+$", "", " ".join(label.split())).title()[:60]
            for raw_n in nums:
                number = re.sub(r"\s+", "", raw_n).strip("-.")
                digits = re.sub(r"\D", "", number)
                if len(digits) < 9 or digits[:10] in seen:
                    continue
                seen.add(digits[:10])
                out.append({"number": number, "label": label})
    return out


SMALL_CAPS = {"SARL", "SA", "SAS", "SNC", "SCI", "AU", "STE", "ETS", "SARLAU", "GIE", "SPA", "CNSS"}


def pretty(name: str) -> str:
    """« STE ATLAS BETON SARL » -> « Atlas Beton SARL » (pour les emails : pas de majuscules partout)."""
    words = []
    parts = _text(name).split()
    if len(parts) > 1 and client_key(parts[0]) in ("STE", "SOCIETE", "ETS"):  # « STE ATLAS » -> « Atlas »
        parts = parts[1:]
    for w in parts:
        u = w.upper().strip(".,")
        words.append(w.upper() if u in SMALL_CAPS - {"STE", "ETS"} else w.capitalize())
    return " ".join(words)


# ------------------------------------------------------------------ import

@dataclass
class ImportReport:
    rows: int = 0
    clients_new: int = 0
    clients_updated: int = 0
    contracts_new: int = 0
    contracts_updated: int = 0
    cancelled: int = 0
    particuliers: int = 0
    pros: int = 0
    with_email: int = 0
    with_phone: int = 0
    contacts_created: int = 0
    contacts_linked: int = 0
    prospects_now_clients: int = 0
    skipped: int = 0
    unknown_branches: list[str] = field(default_factory=list)
    extra_columns: list[str] = field(default_factory=list)
    has_premium: bool = False
    has_due: bool = False
    duplicates: list[list[str]] = field(default_factory=list)

    def as_dict(self) -> dict:
        return dict(self.__dict__)


def import_file(s: Session, path: Path, now: datetime | None = None) -> ImportReport:
    now = now or utcnow()
    headers, rows = read_rows(path)
    cols = map_columns(headers)
    known = set(cols.values())
    extra = [(i, h) for i, h in enumerate(headers) if i not in known and h]
    rep = ImportReport(rows=len(rows), extra_columns=[h for _, h in extra],
                       has_premium="premium" in cols, has_due="due" in cols)

    def get(r, f):
        i = cols.get(f)
        return r[i] if i is not None and i < len(r) else None

    clients = {c.key: c for c in s.scalars(select(PortfolioClient))}
    contracts = {(c.insurer, c.policy): c for c in s.scalars(select(PortfolioContract))}
    touched: dict[str, PortfolioClient] = {}
    notes: dict[str, list[str]] = defaultdict(list)
    phones: dict[str, list] = defaultdict(list)
    unknown: Counter = Counter()
    parsed: list[tuple] = []
    kept_email: dict[str, str | None] = {}

    for r in rows:
        name = _text(get(r, "client"))
        policy = _text(get(r, "policy"))
        insurer = _up(get(r, "insurer"))
        key = client_key(name)
        if not key or not policy or not insurer:
            rep.skipped += 1
            continue
        c = clients.get(key)
        if c is None:
            c = PortfolioClient(key=key, name=name[:255], phones=[], note="", created_at=now)
            s.add(c)
            clients[key] = c
            rep.clients_new += 1
        elif key not in touched:
            rep.clients_updated += 1
        if key not in touched:
            touched[key] = c
            kept_email[key] = c.email  # noté dans l'appli : gardé si DIAMM n'en a pas
            c.email = None
        c.name = name[:255]
        if "particulier" in cols:
            c.segment = "particulier" if _yes(get(r, "particulier")) else "pro"
        elif c.segment is None:
            c.segment = "pro" if re.search(r"\b(STE|SOCIETE|SARL|SA|SAS|ETS|GROUPE|ASSOCIATION|COOPERATIVE)\b", key) else "particulier"
        c.email = c.email or first_email(get(r, "email"))
        phones[key] += phones_of(get(r, "tel1"), get(r, "tel2"))
        for extra_note in [_text(get(r, f)) for f in ("tel1", "tel2") if not phones_of(get(r, f))] + [_text(get(r, "note"))]:
            if len(extra_note) > 1 and extra_note not in notes[key]:  # un nom sans numéro, « De la part de… »
                notes[key].append(extra_note)
        c.seen_at = now
        c.updated_at = now
        parsed.append((key, insurer, policy, r))

    s.flush()  # les nouveaux clients reçoivent leur numéro
    for key, insurer, policy, r in parsed:
        branch, category = _up(get(r, "branch")), _up(get(r, "category"))
        fam = family_of(branch, category)
        if branch and branch not in FAMILIES:
            unknown[branch] += 1
        ck = (insurer[:120], policy[:80])
        ct = contracts.get(ck)
        if ct is None:
            ct = PortfolioContract(policy=policy[:80], insurer=insurer[:120], created_at=now)
            s.add(ct)
            contracts[ck] = ct
            rep.contracts_new += 1
        else:
            rep.contracts_updated += 1
        ct.client_id = clients[key].id
        ct.category, ct.branch, ct.family = category[:120], branch[:120], fam[:60]
        ct.fixed_term = _yes(get(r, "fixed"))
        ct.fleet = _yes(get(r, "fleet"))
        ct.cancelled_on = _date(get(r, "cancelled_on"))
        ct.cancelled = _yes(get(r, "cancelled")) or (ct.cancelled_on is not None and ct.cancelled_on <= now.date())
        # V3.13 : une case vide de l'export n'efface jamais ce qui a été saisi dans l'appli
        if "premium" in cols and _amount(get(r, "premium")) is not None:
            ct.premium = _amount(get(r, "premium"))
        for col, attr in (("due", "due_date"), ("start", "start_date"), ("subscribed", "subscribed_on"),
                          ("last_claim", "last_claim_on")):
            if col in cols and _date(get(r, col)):
                setattr(ct, attr, _date(get(r, col)))
        if "aperiteur" in cols and _text(get(r, "aperiteur")):
            ct.aperiteur_no = _text(get(r, "aperiteur"))[:80]
        if "coinsurance" in cols and _text(get(r, "coinsurance")):
            ct.coinsurance = _yes(get(r, "coinsurance"))
        ct.raw = {h: _text(r[i]) for i, h in extra if i < len(r) and _text(r[i])}
        ct.seen_at = now
        rep.cancelled += ct.cancelled

    for key, c in touched.items():
        c.email = c.email or kept_email.get(key)
        uniq, seen = [], set()
        for p in phones[key]:
            d = re.sub(r"\D", "", p["number"])[:10]
            if d not in seen:
                seen.add(d)
                uniq.append(p)
        c.phones = uniq[:6]
        c.note = " · ".join(notes[key])[:2000]
    s.flush()

    seg = Counter(c.segment for c in touched.values())
    rep.particuliers, rep.pros = seg["particulier"], seg["pro"]
    rep.with_email = sum(1 for c in touched.values() if c.email)
    rep.with_phone = sum(1 for c in touched.values() if c.phones)
    rep.unknown_branches = [b for b, _ in unknown.most_common(30)]
    rep.duplicates = suspected_duplicates(list(touched.values()))[:50]
    _link_contacts(s, [c for c in touched.values() if c.email], rep)
    return rep


_LEGAL = re.compile(r"\b(STE|SOCIETE|STE|SARL|AU|SA|SAS|SNC|ETS|ETABLISSEMENTS?|MR|MME|M|MLLE|GROUPE)\b")


def suspected_duplicates(clients: list[PortfolioClient]) -> list[list[str]]:
    """Noms qui ne diffèrent que par la forme juridique, la civilité ou l'ordre des mots."""
    groups: dict[str, list[str]] = defaultdict(list)
    for c in clients:
        k = " ".join(sorted(_LEGAL.sub(" ", c.key).split()))
        if k:
            groups[k].append(c.name)
    return [sorted(g) for g in groups.values() if len(g) > 1]


def _link_contacts(s: Session, clients: list[PortfolioClient], rep: ImportReport) -> None:
    from app import companies_service
    from app import contacts_service as cs
    for c in clients:
        contact = s.scalars(select(Contact).where(Contact.email == c.email)).first()
        if contact is None:
            data = {"email": c.email, "kind": "client",
                    "phone": c.phones[0]["number"] if c.phones else None}
            if c.segment == "pro":
                data["company"] = pretty(c.name)
            else:
                data["last_name"] = pretty(c.name)
            try:
                contact, _ = cs.create_contact(s, data, SOURCE)
            except cs.ContactInvalid:
                continue
            rep.contacts_created += 1
        else:
            rep.contacts_linked += 1
            if contact.kind == "prospect":
                companies_service.set_contact_kind(s, contact, "client")
                rep.prospects_now_clients += 1
        c.contact_id = contact.id
    s.flush()


# ------------------------------------------------------------------ analyse

@dataclass
class ClientView:
    c: PortfolioClient
    active: list[PortfolioContract]
    all: list[PortfolioContract]

    @property
    def families(self) -> set[str]:
        return {x.family for x in self.active if x.family}


def load(s: Session) -> list[ClientView]:
    by: dict[int, list[PortfolioContract]] = defaultdict(list)
    for ct in s.scalars(select(PortfolioContract)):
        by[ct.client_id].append(ct)
    return [ClientView(c, [x for x in by[c.id] if not x.cancelled], by[c.id])
            for c in s.scalars(select(PortfolioClient).order_by(PortfolioClient.name))]


def _reach(views: list[ClientView]) -> dict:
    return {"count": len(views), "email": sum(1 for v in views if v.c.email),
            "phone": sum(1 for v in views if v.c.phones)}


def summary(s: Session, today: date | None = None) -> dict:
    today = today or utcnow().date()
    views = load(s)
    active = [v for v in views if v.active]
    seg = {k: [v for v in active if v.c.segment == k] for k in ("particulier", "pro")}
    contracts = [x for v in active for x in v.active]
    fam_rows = []
    fams = Counter(f for v in active for f in v.families)
    for f, _ in fams.most_common():
        row = {"family": f, "contracts": sum(1 for x in contracts if x.family == f)}
        for k, vs in seg.items():
            n = sum(1 for v in vs if f in v.families)
            row[k] = {"clients": n, "pct": round(100 * n / len(vs)) if vs else 0}
        fam_rows.append(row)
    ins = Counter(x.insurer for x in contracts)
    ins_clients = {i: len({x.client_id for x in contracts if x.insurer == i}) for i in ins}
    per_client = {k: dict(sorted(Counter(min(len(v.families), 6) for v in vs).items())) for k, vs in seg.items()}
    premium = [x.premium for x in contracts if x.premium is not None]
    due60 = [x for x in contracts if x.due_date and today <= x.due_date <= today + timedelta(days=60)]
    calls = list(s.scalars(select(PortfolioCall)))
    opps = []
    for r in RULES:
        m = [v for v in active if rule_matches(r, v.c.segment, v.families)]
        mine = [x for x in calls if x.rule == r.key]
        opps.append({"key": r.key, "label": r.label, "pitch": r.pitch, "segment": r.segment, **_reach(m),
                     "called": len({x.client_id for x in mine}),
                     "interested": len({x.client_id for x in mine if x.outcome == "interested"})})
    top = sorted(active, key=lambda v: (-len(v.active), v.c.name))[:10]
    last = max((v.c.seen_at for v in views if v.c.seen_at), default=None)
    return {
        "imported_at": last.isoformat() if last else None,
        "clients": len(views), "active_clients": len(active), "contracts": len(contracts),
        "cancelled": sum(1 for v in views for x in v.all if x.cancelled),
        "segments": {k: {**_reach(vs), "contracts": sum(len(v.active) for v in vs),
                         "mono": sum(1 for v in vs if len(v.families) == 1)} for k, vs in seg.items()},
        "reach": _reach(active),
        "families": fam_rows,
        "insurers": [{"insurer": i, "contracts": n, "clients": ins_clients[i]} for i, n in ins.most_common()],
        "families_per_client": per_client,
        "premium_total": round(sum(premium), 2) if premium else None,
        "due_60": len(due60),
        "opportunities": opps,
        "top_clients": [{"id": v.c.id, "name": v.c.name, "segment": v.c.segment, "contracts": len(v.active),
                         "families": len(v.families)} for v in top],
        "all_families": sorted({f for v in active for f in v.families}),
        "callbacks_due": sum(1 for x in calls if not x.callback_done and x.callback_on and x.callback_on <= today),
        "calls": len(calls),
    }


# ------------------------------------------------------------------ appels (listes d'appels)

OUTCOME_LABELS = {"interested": "Intéressé", "callback": "À rappeler", "not_interested": "Pas intéressé",
                  "no_answer": "Pas de réponse", "wrong_number": "Mauvais numéro", "done": "Traité"}


def last_calls(s: Session) -> dict[int, PortfolioCall]:
    out: dict[int, PortfolioCall] = {}
    for c in s.scalars(select(PortfolioCall).order_by(PortfolioCall.created_at, PortfolioCall.id)):
        out[c.client_id] = c
    return out


def _call_json(c: PortfolioCall | None, names: dict | None = None) -> dict | None:
    if c is None:
        return None
    return {"id": c.id, "outcome": c.outcome, "label": OUTCOME_LABELS.get(c.outcome, c.outcome), "note": c.note,
            "callback_on": c.callback_on.isoformat() if c.callback_on else None, "callback_done": c.callback_done,
            "rule": c.rule, "at": c.created_at.isoformat() if c.created_at else None,
            "by": (names or {}).get(c.user_id)}


def _user_names(s: Session) -> dict[int, str]:
    from app.models import AppUser
    return {u.id: (u.full_name or u.email.split("@")[0]) for u in s.scalars(select(AppUser).execution_options(oddo_all=True))}


def set_email(s: Session, c: PortfolioClient, email: str | None) -> None:
    """Email noté (pendant un appel, sur la fiche) : le client devient joignable par les campagnes.
    Un réimport DIAMM ne l'efface pas si DIAMM n'a toujours pas d'email pour lui."""
    from app.importer import EMAIL_RE
    email = (email or "").strip().lower() or None
    if email and not EMAIL_RE.match(email):
        raise PortfolioError("Adresse email invalide.")
    c.email = email
    c.updated_at = utcnow()
    if email:
        _link_contacts(s, [c], ImportReport())
    else:
        c.contact_id = None


def log_call(s: Session, c: PortfolioClient, outcome: str, note: str = "", callback_on: date | None = None,
             rule: str | None = None, email: str | None = None, now: datetime | None = None) -> PortfolioCall:
    from app.current import user_id
    if outcome not in CALL_OUTCOMES:
        raise PortfolioError("Résultat d'appel inconnu.")
    if outcome == "callback" and not callback_on:
        raise PortfolioError("Indiquez la date du rappel.")
    if rule and rule not in {r.key for r in RULES}:
        rule = None
    for old in s.scalars(select(PortfolioCall).where(PortfolioCall.client_id == c.id, PortfolioCall.callback_done.is_(False),
                                                     PortfolioCall.callback_on.is_not(None))):
        old.callback_done = True  # un nouvel appel solde les rappels prévus
    call = PortfolioCall(client_id=c.id, user_id=user_id(), outcome=outcome, note=(note or "").strip()[:2000],
                         callback_on=callback_on if outcome in ("callback", "interested") else None, rule=rule,
                         created_at=now or utcnow())
    s.add(call)
    if email:
        set_email(s, c, email)
    s.flush()
    return call


def callbacks(s: Session, until: date, mine: bool = False) -> list[dict]:
    """Rappels prévus jusqu'à `until` (inclus), les plus anciens d'abord."""
    from app.current import user_id
    q = select(PortfolioCall, PortfolioClient).join(PortfolioClient, PortfolioClient.id == PortfolioCall.client_id).where(
        PortfolioCall.callback_done.is_(False), PortfolioCall.callback_on.is_not(None), PortfolioCall.callback_on <= until)
    if mine and user_id() is not None:
        q = q.where(PortfolioCall.user_id == user_id())
    names = _user_names(s)
    return [{"client": {"id": c.id, "name": c.name, "segment": c.segment,
                        "phone": c.phones[0]["number"] if c.phones else None}, **_call_json(call, names)}
            for call, c in s.execute(q.order_by(PortfolioCall.callback_on, PortfolioCall.id))]


def _row(v: ClientView, last: PortfolioCall | None = None, names: dict | None = None) -> dict:
    return {"last_call": _call_json(last, names), "id": v.c.id, "name": v.c.name, "segment": v.c.segment, "email": v.c.email,
            "phone": v.c.phones[0]["number"] if v.c.phones else None, "contracts": len(v.active),
            "cancelled": len(v.all) - len(v.active), "families": sorted(v.families), "contact_id": v.c.contact_id,
            "premium": round(sum(x.premium for x in v.active if x.premium), 2) or None}


def search(s: Session, q: str = "", segment: str = "", has: str = "", lacks: str = "", rule: str = "",
           reach: str = "", ids: list[int] | None = None, called: str = "", last: dict | None = None) -> list[ClientView]:
    views = [v for v in load(s) if v.active]
    r = next((x for x in RULES if x.key == rule), None)
    qk = client_key(q)
    out = []
    for v in views:
        if ids is not None and v.c.id not in ids:
            continue
        if segment and v.c.segment != segment:
            continue
        if has and has not in v.families or lacks and lacks in v.families:
            continue
        if r and not rule_matches(r, v.c.segment, v.families):
            continue
        if reach == "email" and not v.c.email or reach == "phone" and not v.c.phones \
                or reach == "phone_only" and (v.c.email or not v.c.phones):
            continue
        if called == "never" and last is not None and v.c.id in last:
            continue
        if called == "yes" and last is not None and v.c.id not in last:
            continue
        if qk and qk not in v.c.key and not (v.c.email and q.lower() in v.c.email) \
                and not any(qk in client_key(x.policy) for x in v.all):
            continue
        out.append(v)
    return out


def clients(s: Session, offset: int = 0, limit: int = 100, calls_first: bool = False, **filters) -> dict:
    last = last_calls(s)
    found = search(s, last=last, **filters)
    if calls_first:  # liste d'appels : jamais appelés d'abord, puis les plus anciens appels
        found.sort(key=lambda v: (v.c.id in last, last[v.c.id].created_at if v.c.id in last else datetime.min, v.c.name))
    else:
        found.sort(key=lambda v: (-len(v.active), v.c.name))
    names = _user_names(s)
    return {"total": len(found), **_reach(found),
            "items": [_row(v, last.get(v.c.id), names) for v in found[offset:offset + limit]]}


def detail(s: Session, client_id: int) -> dict | None:
    c = s.get(PortfolioClient, client_id)
    if c is None or c.org_id != _org():
        return None
    allc = list(s.scalars(select(PortfolioContract).where(PortfolioContract.client_id == c.id)
                          .order_by(PortfolioContract.cancelled, PortfolioContract.family, PortfolioContract.branch)))
    v = ClientView(c, [x for x in allc if not x.cancelled], allc)
    opps = [{"key": r.key, "label": r.label, "pitch": r.pitch} for r in RULES
            if not r.mono and rule_matches(r, c.segment, v.families)]
    names = _user_names(s)
    amendments: dict[int, list[PortfolioAmendment]] = defaultdict(list)
    if allc:
        for a in s.scalars(select(PortfolioAmendment).where(PortfolioAmendment.contract_id.in_([x.id for x in allc]))
                           .order_by(PortfolioAmendment.effective_on.desc(), PortfolioAmendment.id.desc())):
            amendments[a.contract_id].append(a)
    calls = list(s.scalars(select(PortfolioCall).where(PortfolioCall.client_id == c.id)
                           .order_by(PortfolioCall.created_at.desc(), PortfolioCall.id.desc())))
    return {**_row(v, calls[0] if calls else None, names), "phones": c.phones, "note": c.note,
            "calls": [_call_json(x, names) for x in calls],
            "missing": [f for f in RELEVANT[c.segment] if f not in v.families],
            "opportunities": opps,
            "items": [{**_contract_extra(s, x, amendments.get(x.id, [])), "id": x.id, "policy": x.policy, "insurer": x.insurer, "category": x.category, "branch": x.branch,
                       "family": x.family, "fleet": x.fleet, "fixed_term": x.fixed_term, "cancelled": x.cancelled,
                       "cancelled_on": x.cancelled_on.isoformat() if x.cancelled_on else None,
                       "premium": x.premium, "due_date": x.due_date.isoformat() if x.due_date else None,
                       "start_date": x.start_date.isoformat() if x.start_date else None, "note": x.note or "",
                       "subscribed_on": x.subscribed_on.isoformat() if x.subscribed_on else None,
                       "last_claim_on": x.last_claim_on.isoformat() if x.last_claim_on else None,
                       "aperiteur_no": x.aperiteur_no or "", "coinsurance": bool(x.coinsurance),
                       "source": x.source} for x in allc],
            "source": c.source}


def _org() -> int:
    from app.current import org_id
    return org_id()


def make_list(s: Session, name: str, views: list[ClientView]) -> tuple[object, int, int]:
    """Liste de contacts (campagne email) avec les clients qui ont un email ; renvoie (liste, ajoutés, sans email)."""
    from app import lists_service as ls
    ids = [v.c.contact_id for v in views if v.c.contact_id]
    cl = ls.create(s, name, ids, source="manual")
    return cl, len(ids), len(views) - len(ids)


# ------------------------------------------------------------------ V3.12 : saisie dans l'appli (relais de DIAMM)

class DuplicateClient(PortfolioError):
    def __init__(self, message: str, existing_id: int):
        super().__init__(message)
        self.existing_id = existing_id


def options(s: Session) -> dict:
    """Compagnies et branches connues, pour les listes de la saisie (branche -> famille)."""
    from app.models import Company
    insurers = {ct.insurer for ct in s.scalars(select(PortfolioContract))}
    insurers |= {_up(c.name) for c in s.scalars(select(Company).where(Company.kind == "insurer"))}
    branches: dict[str, str] = {b: f for b, f in FAMILIES.items()}
    cats: dict[str, str] = {}
    for b, cat in s.execute(select(PortfolioContract.branch, PortfolioContract.category).distinct()):
        if b:
            branches.setdefault(b, family_of(b, cat))
            cats.setdefault(b, cat)
    by_family: dict[str, list[str]] = defaultdict(list)
    for b, f in sorted(branches.items()):
        by_family[f].append(b)
    return {"insurers": sorted(i for i in insurers if i),
            "families": [{"family": f, "branches": bs} for f, bs in sorted(by_family.items())],
            "categories": cats}


def _phones_in(values) -> list[dict]:
    out = []
    for p in values or []:
        if isinstance(p, dict):
            got = phones_of(p.get("number"))
            if got:
                out.append({"number": got[0]["number"], "label": _text(p.get("label"))[:60]})
        else:
            out += phones_of(p)
    seen, uniq = set(), []
    for p in out:
        d = re.sub(r"\D", "", p["number"])[:10]
        if d not in seen:
            seen.add(d)
            uniq.append(p)
    return uniq[:6]


def _client_fields(s: Session, c: PortfolioClient, data: dict) -> None:
    if "name" in data:
        name = _text(data.get("name"))
        key = client_key(name)
        if not key:
            raise PortfolioError("Indiquez le nom du client.")
        other = s.scalars(select(PortfolioClient).where(PortfolioClient.key == key)).first()
        if other is not None and other.id != c.id:
            raise DuplicateClient(f"« {other.name} » existe déjà dans le portefeuille.", other.id)
        c.name, c.key = name[:255], key
    if "segment" in data:
        if data["segment"] not in ("particulier", "pro"):
            raise PortfolioError("Particulier ou entreprise ?")
        c.segment = data["segment"]
    if "phones" in data:
        c.phones = _phones_in(data.get("phones"))
    if "note" in data:
        c.note = _text(data.get("note"))[:2000]
    c.updated_at = utcnow()


def create_client(s: Session, data: dict) -> PortfolioClient:
    c = PortfolioClient(phones=[], note="", source="appli", segment="particulier", created_at=utcnow())
    _client_fields(s, c, {"segment": "particulier", **data, "name": data.get("name")})
    s.add(c)
    s.flush()
    if data.get("email"):
        set_email(s, c, data["email"])
    return c


def update_client(s: Session, c: PortfolioClient, data: dict) -> None:
    _client_fields(s, c, data)
    if "email" in data and (data.get("email") or None) != c.email:
        set_email(s, c, data.get("email"))
    s.flush()


def _contract_fields(s: Session, ct: PortfolioContract, data: dict) -> None:
    if "insurer" in data or "policy" in data:
        insurer = _up(data.get("insurer", ct.insurer))[:120]
        policy = _text(data.get("policy", ct.policy))[:80]
        if not insurer or not policy:
            raise PortfolioError("Indiquez la compagnie et le n° de police.")
        other = s.scalars(select(PortfolioContract).where(PortfolioContract.insurer == insurer,
                                                          PortfolioContract.policy == policy)).first()
        if other is not None and other.id != ct.id:
            raise PortfolioError(f"La police {policy} chez {insurer} existe déjà (client n° {other.client_id}).")
        ct.insurer, ct.policy = insurer, policy
    if "branch" in data:
        branch = _up(data.get("branch"))[:120]
        if not branch:
            raise PortfolioError("Indiquez la branche.")
        cat = _up(data.get("category")) or options_category(s, branch)
        ct.branch, ct.category = branch, cat[:120]
        ct.family = family_of(branch, cat)[:60]
    for f in ("fleet", "fixed_term"):
        if f in data:
            setattr(ct, f, bool(data[f]))
    for f in ("start_date", "due_date", "subscribed_on", "last_claim_on"):
        if f in data:
            setattr(ct, f, _date(data[f]) if data[f] else None)
    if "premium" in data:
        ct.premium = _amount(data["premium"]) if data["premium"] not in (None, "") else None
    if "note" in data:
        ct.note = _text(data.get("note"))[:2000]
    if "aperiteur_no" in data:
        ct.aperiteur_no = _text(data.get("aperiteur_no"))[:80]
    if "coinsurance" in data:
        ct.coinsurance = bool(data["coinsurance"])
    if "attachment_ids" in data:  # V3.13 : contrat scanné, conditions particulières…
        ct.attachment_ids = _files_in(s, data.get("attachment_ids"))


def options_category(s: Session, branch: str) -> str:
    cat = s.scalars(select(PortfolioContract.category).where(PortfolioContract.branch == branch,
                                                             PortfolioContract.category != "")).first()
    return cat or ""


def add_contract(s: Session, c: PortfolioClient, data: dict) -> PortfolioContract:
    ct = PortfolioContract(client_id=c.id, source="appli", raw={}, created_at=utcnow(), note="")
    _contract_fields(s, ct, {"insurer": data.get("insurer"), "policy": data.get("policy"),
                             "branch": data.get("branch"), **data})
    s.add(ct)
    c.updated_at = utcnow()
    s.flush()
    return ct


def update_contract(s: Session, ct: PortfolioContract, data: dict) -> None:
    _contract_fields(s, ct, data)
    if "cancelled" in data:
        ct.cancelled = bool(data["cancelled"])
        ct.cancelled_on = (_date(data.get("cancelled_on")) or utcnow().date()) if ct.cancelled else None
    s.flush()


def delete_contract(s: Session, ct: PortfolioContract) -> None:
    if ct.source != "appli":
        raise PortfolioError("Un contrat venu de DIAMM ne se supprime pas : résiliez-le.")
    s.delete(ct)
    s.flush()


# ------------------------------------------------------------------ avenants et pièces jointes (V3.13)

# Nature de l'avenant (V3.13, Omar : « renouvellement, modification, ajout ou retrait d'un véhicule… »)
AMENDMENT_KINDS = ("Renouvellement", "Modification", "Ajout de véhicule (flotte)", "Retrait de véhicule (flotte)",
                   "Changement de garanties", "Changement de capital", "Changement d'adresse ou d'assuré",
                   "Ajout ou retrait de personnel", "Suspension", "Remise en vigueur", "Autre")
MAX_FILES = 20


def _files_in(s: Session, ids) -> list[int]:
    """Numéros de pièces jointes déjà déposées (/api/attachments) ; refuse un numéro inconnu."""
    from app import attachments_service
    clean = list(dict.fromkeys(int(x) for x in (ids or []) if str(x).isdigit()))[:MAX_FILES]
    try:
        attachments_service.get_many(s, clean)
    except attachments_service.AttachmentError as exc:
        raise PortfolioError(str(exc)) from None
    return clean


def _files_json(s: Session, ids) -> list[dict]:
    from app import attachments_service
    out = []
    for i in ids or []:
        try:
            out += [attachments_service.as_json(a) for a in attachments_service.get_many(s, [i])]
        except attachments_service.AttachmentError:
            continue  # fichier disparu du disque : on n'empêche pas d'afficher le reste
    return out


def _amendment_json(s: Session, a: PortfolioAmendment, names: dict | None = None) -> dict:
    return {"id": a.id, "number": a.number, "effective_on": a.effective_on.isoformat() if a.effective_on else None,
            "kind": a.kind, "description": a.description, "premium_delta": a.premium_delta,
            "files": _files_json(s, a.attachment_ids), "by": (names or {}).get(a.user_id),
            "at": a.created_at.isoformat() if a.created_at else None}


def _contract_extra(s: Session, ct: PortfolioContract, amendments: list[PortfolioAmendment]) -> dict:
    deltas = [a.premium_delta for a in amendments if a.premium_delta is not None]
    return {"files": _files_json(s, ct.attachment_ids), "amendments": [_amendment_json(s, a) for a in amendments],
            "amendments_premium": round(sum(deltas), 2) if deltas else None}


def set_contract_files(s: Session, ct: PortfolioContract, ids) -> None:
    ct.attachment_ids = _files_in(s, ids)
    s.flush()


def _amendment_fields(s: Session, a: PortfolioAmendment, data: dict) -> None:
    if "effective_on" in data:
        a.effective_on = _date(data["effective_on"]) if data["effective_on"] else None
    if "kind" in data:
        a.kind = _text(data.get("kind"))[:60]
    if "number" in data:
        a.number = _text(data.get("number"))[:60]
    if "description" in data:
        a.description = (data.get("description") or "").strip()[:4000]
    if "premium_delta" in data:
        a.premium_delta = _amount(data["premium_delta"]) if data["premium_delta"] not in (None, "") else None
    if "attachment_ids" in data:
        a.attachment_ids = _files_in(s, data.get("attachment_ids"))
    if not a.effective_on:
        raise PortfolioError("Indiquez la date d'effet de l'avenant.")
    if not a.kind and not a.description:
        raise PortfolioError("Indiquez la nature de l'avenant.")


def add_amendment(s: Session, ct: PortfolioContract, data: dict) -> PortfolioAmendment:
    from app.current import user_id
    a = PortfolioAmendment(contract_id=ct.id, user_id=user_id(), created_at=utcnow(), attachment_ids=[], number="",
                           kind="", description="")
    _amendment_fields(s, a, {"effective_on": None, **data})
    s.add(a)
    s.flush()
    return a


def update_amendment(s: Session, a: PortfolioAmendment, data: dict) -> None:
    _amendment_fields(s, a, data)
    s.flush()

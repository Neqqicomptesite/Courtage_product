"""Import de contacts depuis Excel (.xlsx) ou CSV (§6.1).

Le travail est découpé en trois fonctions pures, testables séparément :
1. read_table()    : fichier -> en-têtes + lignes (valeur affichée ET lien hypertexte) ;
2. auto_mapping()  : devine à quel champ correspond chaque colonne ;
3. plan_import()   : calcule ce qui VA se passer (nouveaux, mis à jour, ignorés…)
                     sans rien écrire. apply_plan() n'écrit qu'après validation.
Séparer « calculer » et « écrire » permet d'afficher un aperçu fidèle avant d'importer.
"""
from __future__ import annotations

import csv
import io
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

import openpyxl
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import suppression
from app.models import Contact, EventLog
from app.seed import SECTOR_BLOCKS, TARGET_BLOCKS

EMPTY_MARKERS = {"", "—", "–", "-", "n/a", "na", "none", "null"}
EMAIL_RE = re.compile(r"^[a-z0-9._%+'-]+@[a-z0-9.-]+\.[a-z]{2,}$")

# Champs de `contact` proposés dans l'écran de correspondance.
CONTACT_FIELDS: list[tuple[str, str]] = [
    ("email", "Email"),
    ("first_name", "Prénom"),
    ("last_name", "Nom"),
    ("company", "Entreprise"),
    ("job_title", "Poste"),
    ("sector", "Secteur"),
    ("sector_family", "Famille de secteur"),
    ("target_segment", "Segment (cible)"),
    ("sequence_code", "Code séquence"),
    ("size_bucket", "Taille"),
    ("wave", "Vague d'envoi"),
    ("email_reliability", "Fiabilité de l'email"),
    ("phone", "Téléphone"),
    ("website", "Site web"),
    ("linkedin_url", "Profil LinkedIn"),
    ("notes", "Notes"),
    ("kind", "Type de contact"),
    ("department", "Service (assureurs)"),
    ("seniority", "Niveau (assureurs)"),
]
# « Type de contact » (V2.3) : libellés acceptés dans un fichier -> code interne
KIND_WORDS = {"prospect": "prospect", "client": "client", "assureur": "insurer", "compagnie": "insurer",
              "compagnie d assurance": "insurer", "partenaire": "partner"}
FIELD_NAMES = {f for f, _ in CONTACT_FIELDS}
URL_FIELDS = {"linkedin_url", "website"}


def norm(text: str) -> str:
    """« Code séquence (cible × secteur) » -> « code sequence cible secteur »."""
    text = unicodedata.normalize("NFKD", str(text)).encode("ascii", "ignore").decode()
    text = re.sub(r"[^a-z0-9]+", " ", text.lower())
    return text.strip()


def slug(text: str) -> str:
    return norm(text).replace(" ", "_") or "colonne"


# En-têtes connus (fichier réel d'Omar + variantes courantes), sous forme normalisée.
AUTO_MAP: dict[str, str] = {
    "prenom": "first_name", "first name": "first_name", "firstname": "first_name",
    "nom": "last_name", "last name": "last_name", "lastname": "last_name", "nom de famille": "last_name",
    "email": "email", "e mail": "email", "mail": "email", "adresse email": "email",
    "entreprise": "company", "societe": "company", "company": "company",
    "poste linkedin": "job_title", "poste": "job_title", "fonction": "job_title", "job title": "job_title",
    "secteur": "sector",
    "famille de secteur": "sector_family",
    "segment cible": "target_segment", "segment": "target_segment", "cible": "target_segment",
    "code sequence cible secteur": "sequence_code", "code sequence": "sequence_code",
    "taille": "size_bucket",
    "vague d envoi": "wave", "vague": "wave",
    "fiabilite de l email": "email_reliability", "fiabilite": "email_reliability",
    "tel standard entreprise": "phone", "telephone": "phone", "tel": "phone",
    "site web": "website", "site": "website", "website": "website",
    "profil linkedin": "linkedin_url", "linkedin": "linkedin_url",
    "notes": "notes", "note": "notes",
    "type de contact": "kind", "type": "kind", "relation": "kind",
    "service": "department", "departement": "department", "department": "department", "pole": "department",
    "niveau": "seniority", "seniorite": "seniority", "seniority": "seniority",
}
# Service / niveau (V2.8) : libellés acceptés -> code interne
DEPARTMENT_WORDS = {"souscription": "souscription", "gestion": "gestion", "production": "production",
                    "maritime": "maritime_transport", "transport": "maritime_transport",
                    "maritime transport": "maritime_transport", "autre": "autre"}
SENIORITY_WORDS = {"junior": "junior", "senior": "senior", "directeur": "directeur", "directrice": "directeur",
                   "directeur de departement": "directeur", "directrice de departement": "directeur",
                   "directeur departement": "directeur", "responsable": "directeur"}
IGNORED_BY_DEFAULT = {"", "#", "n", "no", "numero"}


# --------------------------------------------------------------------------- lecture

@dataclass
class Cell:
    value: str | None
    link: str | None = None


@dataclass
class Table:
    sheets: list[str]
    sheet: str | None
    headers: list[str]
    rows: list[list[Cell]]
    header_row: int  # numéro de ligne (1 = première) de l'en-tête, pour les messages


def _to_text(v) -> str | None:
    if v is None:
        return None
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    if isinstance(v, datetime):
        v = v.date()
    if isinstance(v, date):
        return v.isoformat()
    text = str(v).strip()
    return None if text.lower() in EMPTY_MARKERS else text


def _find_header(rows: list[list[Cell]]) -> int:
    """Index de la ligne d'en-tête : la première (parmi les 10 premières) qui contient « Email »."""
    for i, row in enumerate(rows[:10]):
        if any(c.value and AUTO_MAP.get(norm(c.value)) == "email" for c in row):
            return i
    return 0


def read_table(path: Path, sheet: str | None = None) -> Table:
    if path.suffix.lower() in (".xlsx", ".xlsm"):
        # read_only=False obligatoire : en mode lecture seule, openpyxl ne lit pas les liens.
        wb = openpyxl.load_workbook(path, read_only=False, data_only=True)
        sheets = wb.sheetnames
        if sheet not in sheets:
            sheet = _guess_sheet(wb)
        ws = wb[sheet]
        raw = [[Cell(_to_text(c.value), c.hyperlink.target if c.hyperlink else None) for c in r]
               for r in ws.iter_rows()]
        wb.close()
    elif path.suffix.lower() == ".csv":
        sheets, sheet = [], None
        raw = [[Cell(_to_text(v)) for v in r] for r in _read_csv(path)]
    else:
        raise ValueError("Format non pris en charge : utilisez un fichier .xlsx ou .csv")

    raw = [r for r in raw if any(c.value or c.link for c in r)]  # lignes vides
    if not raw:
        return Table(sheets, sheet, [], [], 1)
    h = _find_header(raw)
    width = max(len(r) for r in raw)
    headers = [(raw[h][i].value if i < len(raw[h]) else None) or f"Colonne {i + 1}" for i in range(width)]
    rows = [r + [Cell(None)] * (width - len(r)) for r in raw[h + 1:]]
    return Table(sheets, sheet, headers, rows, h + 1)


def _guess_sheet(wb) -> str:
    """Première feuille dont une des 10 premières lignes contient une colonne Email."""
    for ws in wb.worksheets:
        for row in ws.iter_rows(max_row=10, values_only=True):
            if any(v and AUTO_MAP.get(norm(str(v))) == "email" for v in row):
                return ws.title
    return wb.sheetnames[0]


def _read_csv(path: Path) -> list[list[str]]:
    data = path.read_bytes()
    # Excel « CSV UTF-8 » ajoute une signature (utf-8-sig) ; l'ancien format est en Windows-1252.
    for encoding in ("utf-8-sig", "cp1252"):
        try:
            text = data.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    try:
        dialect = csv.Sniffer().sniff(text[:5000], delimiters=",;\t")
        delimiter = dialect.delimiter
    except csv.Error:
        delimiter = ";" if text[:2000].count(";") > text[:2000].count(",") else ","
    return list(csv.reader(io.StringIO(text), delimiter=delimiter))


# ------------------------------------------------------------------ correspondance

def auto_mapping(headers: list[str]) -> list[str]:
    """Pour chaque colonne : « field:<champ> », « custom:<clé> » ou « ignore »."""
    out, used = [], set()
    for h in headers:
        n = norm(h)
        target = AUTO_MAP.get(n)
        if target is None and n.startswith("taille"):  # « Taille* », « Taille (effectif) »…
            target = "size_bucket"
        if target and target not in used:
            used.add(target)
            out.append(f"field:{target}")
        elif n in IGNORED_BY_DEFAULT or n.startswith("colonne "):
            out.append("ignore")
        else:
            out.append(f"custom:{slug(h)}")
    return out


def validate_mapping(mapping: list[str]) -> list[str]:
    errors = []
    fields = [m[6:] for m in mapping if m.startswith("field:")]
    if "email" not in fields:
        errors.append("Aucune colonne n'est associée au champ Email.")
    dups = sorted({f for f in fields if fields.count(f) > 1})
    if dups:
        errors.append("Plusieurs colonnes associées au même champ : " + ", ".join(dups))
    for m in mapping:
        if m.startswith("field:") and m[6:] not in FIELD_NAMES:
            errors.append(f"Champ inconnu : {m[6:]}")
    return errors


# ------------------------------------------------------------------------ aperçu

@dataclass
class RowPlan:
    row_no: int                 # numéro de ligne dans le fichier (pour retrouver la ligne)
    email: str | None
    values: dict
    custom: dict
    action: str                 # "new" | "update" | "ignore"
    reason: str = ""
    suppressed: bool = False
    warnings: list[str] = field(default_factory=list)


@dataclass
class ImportPlan:
    rows: list[RowPlan]
    custom_labels: dict[str, str] = field(default_factory=dict)  # clé -> en-tête d'origine

    def of(self, action: str) -> list[RowPlan]:
        return [r for r in self.rows if r.action == action]

    @property
    def suppressed(self) -> list[RowPlan]:
        return [r for r in self.rows if r.suppressed and r.action != "ignore"]

    @property
    def warned(self) -> list[RowPlan]:
        return [r for r in self.rows if r.warnings and r.action != "ignore"]


def _clean_email(cell: Cell) -> str | None:
    value = cell.value or ""
    if not value and cell.link and cell.link.lower().startswith("mailto:"):
        value = cell.link[7:]
    value = value.strip().lower()
    if value.startswith("mailto:"):
        value = value[7:]
    return value or None


def _cell_value(cell: Cell, fieldname: str) -> str | None:
    # Pour les liens : si la cellule affiche « Voir le profil », la vraie adresse est dans le lien.
    if fieldname in URL_FIELDS and cell.link and not (cell.value or "").lower().startswith(("http", "www.")):
        return cell.link
    return cell.value


def check_sequence_code(code: str | None) -> str | None:
    if not code:
        return "Code séquence manquant"
    target, _, sector = code.upper().partition("-")
    if target not in TARGET_BLOCKS or sector not in SECTOR_BLOCKS:
        return f"Code séquence « {code} » non reconnu (attendu CIBLE-SECTEUR, ex. FIN-IND)"
    return None


def plan_import(session: Session, table: Table, mapping: list[str]) -> ImportPlan:
    existing = {e for e in session.scalars(select(Contact.email))}
    supp = suppression.suppressed_keys(session)
    seen: dict[str, int] = {}
    rows: list[RowPlan] = []

    for i, row in enumerate(table.rows):
        row_no = table.header_row + 1 + i
        values, custom, email, warnings = {}, {}, None, []
        for cell, target, header in zip(row, mapping, table.headers):
            if target == "field:email":
                email = _clean_email(cell)
            elif target.startswith("field:"):
                v = _cell_value(cell, target[6:])
                if v is not None:
                    values[target[6:]] = v
            elif target.startswith("custom:"):
                v = cell.value or cell.link
                if v is not None:
                    custom[target[7:]] = v
        if "kind" in values:
            kind = KIND_WORDS.get(norm(values["kind"]))
            if kind:
                values["kind"] = kind
            else:
                warnings.append(f"Type « {values.pop('kind')} » inconnu : Prospect par défaut")
        for f, words, label in (("department", DEPARTMENT_WORDS, "Service"), ("seniority", SENIORITY_WORDS, "Niveau")):
            if f in values:
                code = words.get(norm(values[f]))
                if code:
                    values[f] = code
                else:
                    warnings.append(f"{label} « {values.pop(f)} » inconnu : ignoré")
        if "sequence_code" in values:
            values["sequence_code"] = values["sequence_code"].upper().replace(" ", "")
        elif values.get("target_segment") and values.get("sector_family"):
            # Pas de colonne code (ou cellule vide) : on le déduit de la cible et du secteur (V2.2).
            from app import vocab  # import local : vocab importe ce module
            derived = vocab.sequence_code(values["target_segment"], values["sector_family"])
            if derived:
                values["sequence_code"] = derived

        plan = RowPlan(row_no, email, values, custom, action="new")
        if not email:
            plan.action, plan.reason = "ignore", "Pas d'email"
        elif not EMAIL_RE.match(email):
            plan.action, plan.reason = "ignore", f"Email invalide : {email}"
        elif suppression.email_hash(email) in supp:
            # Personne effacée à sa demande : on ne recrée pas ses données (droit d'effacement).
            plan.action, plan.reason = "ignore", "Contact effacé à sa demande (droit d'effacement)"
        elif email in seen:
            plan.action, plan.reason = "ignore", f"Doublon de la ligne {seen[email]} dans le fichier"
        else:
            seen[email] = row_no
            plan.action = "update" if email in existing else "new"
            plan.suppressed = suppression.is_suppressed(email, supp)
            plan.warnings.extend(warnings)
            if any(m == "field:sequence_code" for m in mapping):
                warning = check_sequence_code(values.get("sequence_code"))
                if warning:
                    plan.warnings.append(warning)
        rows.append(plan)
    labels = {m[7:]: h for m, h in zip(mapping, table.headers) if m.startswith("custom:")}
    return ImportPlan(rows, labels)


def apply_plan(session: Session, plan: ImportPlan, source: str) -> dict[str, int]:
    """Écrit les contacts. Règle de mise à jour : une cellule vide dans le nouveau fichier
    n'efface PAS une valeur déjà connue (on ne perd jamais d'information par ré-import)."""
    counts = {"new": 0, "update": 0, "ignore": 0}
    by_email = {c.email: c for c in session.scalars(select(Contact))}
    for r in plan.rows:
        counts[r.action] += 1
        if r.action == "ignore":
            continue
        contact = by_email.get(r.email)
        if contact is None:
            contact = Contact(email=r.email, source=source, custom={})
            session.add(contact)
            by_email[r.email] = contact
        for k, v in r.values.items():
            if k != "kind":  # le type passe par companies_service (arrêt des séquences si non-prospect)
                setattr(contact, k, v)
        if r.custom:
            # Réaffecter un NOUVEAU dict : SQLAlchemy ne détecte pas la modification
            # « sur place » d'un dict JSON (contact.custom[k] = v ne serait pas sauvegardé).
            contact.custom = {**(contact.custom or {}), **r.custom}
    session.flush()
    # Rattachement aux entreprises (V2.3) : nom replié, type hérité si le fichier ne le donne pas.
    from app import companies_service  # import local : companies_service importe contacts_service
    for r in plan.rows:
        if r.action != "ignore":
            contact = by_email[r.email]
            companies_service.link(session, contact, kind_explicit="kind" in r.values)
            if "kind" in r.values:
                companies_service.set_contact_kind(session, contact, r.values["kind"])
    if plan.custom_labels:
        from app import settings_store  # import local : évite un import circulaire au chargement
        labels = settings_store.get(session, "custom_field_labels")
        settings_store.set_(session, "custom_field_labels", {**labels, **plan.custom_labels})
    session.add(EventLog(level="info", entity="import",
                         text=f"Import « {source} » : {counts['new']} nouveaux, "
                              f"{counts['update']} mis à jour, {counts['ignore']} ignorés"))
    return counts

"""Modèle Excel à remplir pour importer des contacts.

Les en-têtes sont exactement ceux que l'import reconnaît : une fois rempli, le fichier
s'importe sans aucun réglage de colonnes. Les listes déroulantes évitent les fautes de
frappe sur la cible, le secteur, la taille, la vague et la fiabilité.
"""
from __future__ import annotations

from io import BytesIO

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation

from app import vocab
from app.companies_service import KIND_LABELS
from app.contacts_service import DEPARTMENT_LABELS, SENIORITY_LABELS

ROWS = 500  # lignes préparées (listes déroulantes et formule du code séquence)
BLUE, GREEN = "244480", "009454"

# (en-tête, largeur, liste déroulante éventuelle)
COLUMNS: list[tuple[str, int, str | None]] = [
    ("Prénom", 14, None),
    ("Nom", 16, None),
    ("Email", 30, None),
    ("Poste", 28, None),
    ("Entreprise", 24, None),
    ("Type de contact", 16, "kinds"),
    ("Service", 20, "departments"),
    ("Niveau", 22, "seniorities"),
    ("Téléphone", 18, None),
    ("Site web", 22, None),
    ("Profil LinkedIn", 28, None),
    ("Secteur", 26, None),
    ("Segment (cible)", 24, "targets"),
    ("Famille de secteur", 28, "sectors"),
    ("Code séquence (cible × secteur)", 16, None),
    ("Taille", 16, "sizes"),
    ("Vague d'envoi", 14, "waves"),
    ("Fiabilité de l'email", 18, "reliability"),
    ("Accroche suggérée", 40, None),
    ("Garanties à évoquer (pistes)", 36, None),
    ("Notes", 30, None),
]


def _col(header: str) -> str:
    return get_column_letter([h for h, _, _ in COLUMNS].index(header) + 1)


def build() -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "Contacts"
    lists = wb.create_sheet("Listes")
    guide = wb.create_sheet("Mode d'emploi")

    # --- feuille des listes (masquée) : sert aux menus déroulants et à la formule du code
    values = {
        "targets": list(vocab.TARGETS.items()),
        "sectors": list(vocab.SECTORS.items()),
        "sizes": [("", v) for v in vocab.SIZES],
        "waves": [("", v) for v in vocab.WAVES],
        "reliability": [("", v) for v in vocab.RELIABILITY],
        "kinds": [("", v) for v in KIND_LABELS.values()],
        "departments": [("", v) for v in DEPARTMENT_LABELS.values()],
        "seniorities": [("", v) for v in SENIORITY_LABELS.values()],
    }
    ranges = {}
    for i, (name, items) in enumerate(values.items()):
        code_col, label_col = get_column_letter(2 * i + 1), get_column_letter(2 * i + 2)
        lists[f"{code_col}1"], lists[f"{label_col}1"] = f"code_{name}", name
        for r, (code, label) in enumerate(items, start=2):
            lists[f"{code_col}{r}"], lists[f"{label_col}{r}"] = code, label
        last = len(items) + 1
        ranges[name] = (f"Listes!${code_col}$2:${code_col}${last}", f"Listes!${label_col}$2:${label_col}${last}")
    lists.sheet_state = "hidden"

    # --- feuille Contacts
    head_fill, head_font = PatternFill("solid", fgColor=BLUE), Font(bold=True, color="FFFFFF")
    for c, (header, width, _) in enumerate(COLUMNS, start=1):
        cell = ws.cell(row=1, column=c, value=header)
        cell.fill, cell.font = head_fill, head_font
        cell.alignment = Alignment(vertical="center", wrap_text=True)
        ws.column_dimensions[get_column_letter(c)].width = width
    ws.row_dimensions[1].height = 32
    ws.freeze_panes = "A2"
    ws.cell(row=1, column=3).fill = PatternFill("solid", fgColor=GREEN)  # l'email est la seule colonne obligatoire

    for header, _, source in COLUMNS:
        if not source:
            continue
        dv = DataValidation(type="list", formula1=f"={ranges[source][1]}", allow_blank=True,
                            showErrorMessage=source in ("targets", "sectors", "kinds"),
                            errorTitle="Valeur inconnue", error="Choisissez une valeur dans la liste.")
        dv.add(f"{_col(header)}2:{_col(header)}{ROWS + 1}")
        ws.add_data_validation(dv)

    # Code séquence calculé : Segment + Famille -> FIN-BTP (l'application le recalcule aussi à l'import).
    t, f, code = _col("Segment (cible)"), _col("Famille de secteur"), _col("Code séquence (cible × secteur)")
    (tc, tl), (sc, sl) = ranges["targets"], ranges["sectors"]
    grey = PatternFill("solid", fgColor="EEF1F6")
    for r in range(2, ROWS + 2):
        ws[f"{code}{r}"] = (f'=IF(OR({t}{r}="",{f}{r}=""),"",IFERROR(INDEX({tc},MATCH({t}{r},{tl},0))'
                            f'&"-"&INDEX({sc},MATCH({f}{r},{sl},0)),""))')
        ws[f"{code}{r}"].fill = grey

    # --- mode d'emploi
    lines = [
        ("Modèle d'import – ODDO Séquences", True),
        ("", False),
        ("1. Remplissez une ligne par personne dans l'onglet « Contacts ». Seule la colonne Email est obligatoire.", False),
        ("2. Choisissez la cible et la famille de secteur dans les listes : le code séquence (gris) se remplit tout seul.", False),
        ("   C'est lui qui choisit la trame et le paragraphe de secteur de chaque email (ex. FIN-BTP).", False),
        ("3. Enregistrez, puis dans l'application : Contacts → Importer → glissez ce fichier.", False),
        ("4. Rien n'est enregistré avant votre confirmation ; un contact déjà connu (même email) est mis à jour,", False),
        ("   et une cellule vide n'efface jamais une information déjà connue.", False),
        ("", False),
        ("Colonnes « Accroche suggérée » et « Garanties à évoquer » : elles deviennent des champs personnalisés,", False),
        ("utilisables dans vos emails avec {{ custom.accroche_suggeree }} et {{ custom.garanties_a_evoquer_pistes }}.", False),
        ("Vous pouvez ajouter d'autres colonnes : chacune devient un champ personnalisé.", False),
        ("", False),
        ("Type de contact : laissez vide pour un prospect. Client, Assureur et Partenaire ne reçoivent jamais de prospection", False),
        ("   (seulement des séquences de gestion ou de souscription).", False),
        ("Service et Niveau : utiles pour les assureurs (Souscription, Gestion… ; Junior, Senior, Directeur de département).", False),
        ("", False),
        ("Fiabilité de l'email : commencez par Bonne, Moyenne, À vérifier, Personnelle ou Générique ;", False),
        ("vous pouvez préciser la source après, ex. « Bonne (Findymail) ».", False),
        ("", False),
        ("Exemple de ligne (fictive, à ne pas importer) :", True),
    ]
    for r, (text, bold) in enumerate(lines, start=1):
        guide.cell(row=r, column=1, value=text).font = Font(bold=bold, size=14 if r == 1 else 11, color=BLUE if r == 1 else None)
    example = ["Salma", "Bennani", "s.bennani@exemple.ma", "Directrice administrative et financière", "Exemple SARL", "Prospect", "", "",
               "+212 522 00 00 00", "exemple.ma", "", "Logistique frigorifique", "Finance & administration",
               "Transport & logistique", "FIN-TRA", "Petite (10–49)", "Vague 1", "Bonne (Findymail)",
               "Revue gratuite de vos contrats d'assurance", "flotte, marchandises transportées", ""]
    start = len(lines) + 1
    for c, ((header, _, _), value) in enumerate(zip(COLUMNS, example), start=1):
        guide.cell(row=start, column=c, value=header).font = Font(bold=True, color="FFFFFF")
        guide.cell(row=start, column=c).fill = head_fill
        guide.cell(row=start + 1, column=c, value=value)
        guide.column_dimensions[get_column_letter(c)].width = max(14, len(str(value)) + 2)

    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()

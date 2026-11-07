"""Vocabulaire des contacts : cibles, familles de secteur, tailles, vagues.

Les libellés sont ceux du fichier de prospection d'Omar (« Finance & administration »,
« Industrie & énergie »…), pour que les filtres regroupent bien les contacts importés et
ceux saisis à la main. Le code séquence (FIN-IND…) se déduit de la cible et du secteur.
"""
from __future__ import annotations

from app.companies_service import KIND_LABELS
from app.contacts_service import DEPARTMENT_LABELS, SENIORITY_LABELS
from app.importer import norm
from app.seed import SECTOR_BLOCKS, TARGET_BLOCKS

TARGETS: dict[str, str] = {"FIN": "Finance & administration", "RH": "RH", "DIR": "Dirigeant"}
SECTORS: dict[str, str] = {
    "IND": "Industrie & énergie",
    "SRV": "Services, IT & conseil",
    "BTP": "BTP & immobilier",
    "COM": "Commerce & distribution",
    "TRA": "Transport & logistique",
    "AGRO": "Agroalimentaire & agriculture",
    "SANTE": "Santé & pharma",
}
SIZES = ["TPE (< 10)", "Petite (10–49)", "Moyenne (50+)"]
WAVES = ["Vague 1", "Vague 2", "Vague 3"]
RELIABILITY = ["Bonne", "Moyenne", "À vérifier", "Personnelle", "Générique"]

assert set(TARGETS) == set(TARGET_BLOCKS) and set(SECTORS) == set(SECTOR_BLOCKS)


def _key(text: str) -> str:
    # « Finance & administration », « Finance et administration », « FIN » -> même clé
    return " ".join(w for w in norm(text).split() if w != "et")


def _lookup(value: str | None, table: dict[str, str], blocks: dict[str, str]) -> str | None:
    if not value:
        return None
    k = _key(value)
    for code in table:
        if k in (_key(code), _key(table[code]), _key(blocks[code])):
            return code
    # « Agroalimentaire » seul, « Santé » seul : on accepte le début du libellé
    for code, label in table.items():
        if _key(label).startswith(k) and len(k) >= 4:
            return code
    return None


def target_code(value: str | None) -> str | None:
    return _lookup(value, TARGETS, TARGET_BLOCKS)


def sector_code(value: str | None) -> str | None:
    return _lookup(value, SECTORS, SECTOR_BLOCKS)


def sequence_code(target: str | None, family: str | None) -> str | None:
    """« Finance & administration » + « BTP & immobilier » -> « FIN-BTP » (None si inconnu)."""
    t, f = target_code(target), sector_code(family)
    return f"{t}-{f}" if t and f else None


def options() -> dict:
    return {
        "targets": [{"value": v, "label": v, "code": k} for k, v in TARGETS.items()],
        "sectors": [{"value": v, "label": v, "code": k} for k, v in SECTORS.items()],
        "sizes": SIZES, "waves": WAVES, "reliability": RELIABILITY,
        "kinds": [{"value": k, "label": v} for k, v in KIND_LABELS.items()],
        "departments": [{"value": k, "label": v} for k, v in DEPARTMENT_LABELS.items()],
        "seniorities": [{"value": k, "label": v} for k, v in SENIORITY_LABELS.items()],
    }


# ------------------------------------------------------------------ fonctions et secteurs ajoutés (V2.9)
# Les listes ci-dessus sont celles de départ. Omar peut en ajouter depuis « Textes personnalisés » :
# chaque ajout est un bloc (content_block) avec un libellé. Au démarrage et après chaque ajout,
# on recharge ces dictionnaires EN PLACE : tous les modules qui les ont importés voient l'ajout.
import re as _re  # noqa: E402
import unicodedata as _ud  # noqa: E402

from app.seed import SECTOR_BLOCKS as _SB, TARGET_BLOCKS as _TB  # noqa: E402

_BASE = (dict(TARGETS), dict(SECTORS), dict(_TB), dict(_SB))


class ProfileError(ValueError):
    pass


def load_custom(session) -> None:
    from sqlalchemy import select

    from app.models import ContentBlock
    for d, base in zip((TARGETS, SECTORS, _TB, _SB), _BASE):
        d.clear()
        d.update(base)
    for b in session.scalars(select(ContentBlock).where(ContentBlock.label.is_not(None)).order_by(ContentBlock.id)):
        if b.kind == "target":
            TARGETS[b.key] = _TB[b.key] = b.label
        else:
            SECTORS[b.key] = _SB[b.key] = b.label


def new_code(label: str, taken: set[str]) -> str:
    """« Achats » -> « ACH » ; « Hôtellerie & tourisme » -> « HOT » ; unique, sans tiret."""
    t = _ud.normalize("NFKD", label).encode("ascii", "ignore").decode().upper()
    words = [w for w in _re.findall(r"[A-Z0-9]+", t) if w not in {"ET", "DE", "DES", "LA", "LE", "LES", "DU"}]
    word = (words[0] if words else "X") + "".join(words[1:2])
    for size in (3, 4, 5):
        if word[:size] not in taken:
            return word[:size]
    code, n = word[:3], 2
    while f"{code}{n}" in taken:
        n += 1
    return f"{code}{n}"


def add_profile(session, kind: str, label: str):
    """Ajoute une fonction (kind=target) ou un secteur (kind=sector) et son texte à rédiger."""
    from app.models import ContentBlock
    label = " ".join((label or "").split())[:120]
    if kind not in ("target", "sector"):
        raise ProfileError("Type inconnu.")
    if not label:
        raise ProfileError("Indiquez un nom.")
    table, blocks = (TARGETS, _TB) if kind == "target" else (SECTORS, _SB)
    if _key(label) in {_key(x) for x in [*table, *table.values(), *blocks.values()]}:
        raise ProfileError(f"« {label} » existe déjà.")
    code = new_code(label, set(TARGETS) | set(SECTORS))
    what = "fonction" if kind == "target" else "secteur"
    b = ContentBlock(kind=kind, key=code, label=label, body=f"À RÉDIGER – texte {what} « {label} » ({code}).")
    session.add(b)
    session.flush()
    load_custom(session)
    return b


def profile_usage(session, block) -> int:
    from sqlalchemy import func, select

    from app.models import Contact
    pattern = f"{block.key}-%" if block.kind == "target" else f"%-{block.key}"
    return session.scalar(select(func.count(Contact.id)).where(Contact.sequence_code.like(pattern))) or 0


def remove_profile(session, block) -> None:
    if not block.label:
        raise ProfileError("Les fonctions et secteurs de départ ne se suppriment pas.")
    n = profile_usage(session, block)
    if n:
        raise ProfileError(f"{n} contact(s) ont ce profil : changez d'abord leur fonction ou leur secteur.")
    session.delete(block)
    session.flush()
    load_custom(session)

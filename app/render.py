"""Rendu des modèles d'email (§6.3).

Syntaxe volontairement minimale (pas Jinja) : un email de prospection n'a pas
besoin de boucles ni de conditions, et une syntaxe simple évite les surprises.

    {{ prenom }}                 valeur du contact
    {{ prenom | "Bonjour" }}     valeur de repli si le champ est vide
    {{ custom.accroche_suggeree }}
    {{ bloc_cible }} / {{ bloc_secteur }}   paragraphes choisis d'après le code séquence

Règle de sécurité : on ne « devine » jamais. Une variable inconnue, une valeur
vide sans repli, un bloc introuvable ou encore marqué « À RÉDIGER » est
SIGNALÉ comme problème. Une campagne avec un problème ne pourra pas être activée (M4).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.models import Contact

VAR_RE = re.compile(r'\{\{\s*([A-Za-z_][A-Za-z0-9_.]*)\s*(?:\|\s*"([^"]*)"\s*)?\}\}')
TODO_MARKER = "À RÉDIGER"

# Variables simples -> attribut du contact
CONTACT_VARS = {
    "prenom": "first_name",
    "nom": "last_name",
    "entreprise": "company",
    "poste": "job_title",
    "secteur": "sector",
}
SPECIAL_VARS = {"signature", "bloc_cible", "bloc_secteur"}
KNOWN_VARS = sorted(set(CONTACT_VARS) | SPECIAL_VARS)


@dataclass
class RenderContext:
    """Tout ce qu'il faut pour rendre les emails d'UN contact."""
    contact: Contact
    signature: str
    target_blocks: dict[str, str]   # {"FIN": "texte…", ...}
    sector_blocks: dict[str, str]   # {"IND": "texte…", ...}

    @property
    def target_key(self) -> str:
        return (self.contact.sequence_code or "").upper().partition("-")[0]

    @property
    def sector_key(self) -> str:
        return (self.contact.sequence_code or "").upper().partition("-")[2]


@dataclass
class Rendered:
    text: str
    problems: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.problems


def _lookup(name: str, ctx: RenderContext, problems: list[str], depth: int) -> str | None:
    if name in CONTACT_VARS:
        return getattr(ctx.contact, CONTACT_VARS[name])
    if name.startswith("custom."):
        return (ctx.contact.custom or {}).get(name[7:])
    if name == "signature":
        return ctx.signature
    if name in ("bloc_cible", "bloc_secteur"):
        if depth > 0:
            problems.append(f"{{{{ {name} }}}} ne peut pas être utilisé à l'intérieur d'un bloc")
            return ""
        key, blocks, label = ((ctx.target_key, ctx.target_blocks, "cible") if name == "bloc_cible"
                              else (ctx.sector_key, ctx.sector_blocks, "secteur"))
        if not key:
            problems.append(f"Code séquence absent : impossible de choisir le bloc {label}")
            return ""
        if key not in blocks:
            problems.append(f"Bloc {label} « {key} » introuvable")
            return ""
        body = blocks[key]
        if TODO_MARKER in body:
            problems.append(f"Bloc {label} « {key} » pas encore rédigé (contient « {TODO_MARKER} »)")
        # Un bloc peut lui-même contenir des variables ({{ entreprise }}…) : on le rend aussi.
        return _render(body, ctx, problems, depth + 1)
    problems.append(f"Variable inconnue : {{{{ {name} }}}}")
    return ""


def _render(template: str, ctx: RenderContext, problems: list[str], depth: int) -> str:
    def replace(m: re.Match) -> str:
        name, fallback = m.group(1), m.group(2)
        value = _lookup(name, ctx, problems, depth)
        if value is None or str(value).strip() == "":
            if fallback is not None:
                return fallback
            if name in CONTACT_VARS or name.startswith("custom."):
                problems.append(f"Valeur manquante pour {{{{ {name} }}}} (ajoutez une valeur de repli : "
                                f'{{{{ {name} | "…" }}}})')
            return ""
        return str(value)

    out = VAR_RE.sub(replace, template)
    # Accolades restantes = variable mal écrite (ex. « {{ prenom } » ou « {{ pré nom }} »)
    for leftover in re.findall(r"\{\{[^}]*\}?\}?", out):
        problems.append(f"Variable mal écrite : {leftover}")
    return out


def render(template: str, ctx: RenderContext) -> Rendered:
    problems: list[str] = []
    text = _render(template, ctx, problems, depth=0)
    # Un bloc vide laisse des lignes vides en trop : on n'en garde jamais plus d'une à la suite.
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    # Même problème signalé plusieurs fois (ex. bloc utilisé deux fois) : une seule ligne.
    return Rendered(text, list(dict.fromkeys(problems)))


# V2.14 : champs à compléter au moment de l'envoi, écrits entre crochets dans le modèle :
# « [N° de police] », « [Banque] »… Tant qu'il en reste un, l'email ne part pas.
PLACEHOLDER_RE = re.compile(r"\[([^\[\]\n]{2,60})\]")


def placeholders(text: str) -> list[str]:
    return list(dict.fromkeys(m.group(1).strip() for m in PLACEHOLDER_RE.finditer(text or "")))


def full_body(rendered_body: str, template: str, signature: str, unsubscribe_line: str) -> str:
    """Corps final : texte + signature (si le modèle ne l'a pas déjà placée) + ligne STOP.

    La ligne de désinscription est TOUJOURS ajoutée (§9 : non supprimable)."""
    parts = [rendered_body]
    if "signature" not in {m.group(1) for m in VAR_RE.finditer(template)} and signature.strip():
        parts.append(signature.strip())
    parts.append(unsubscribe_line.strip())
    return "\n\n".join(p for p in parts if p)


def subject_for_reply(first_subject: str) -> str:
    return first_subject if first_subject.lower().startswith("re:") else f"Re: {first_subject}"


def count_links(text: str) -> int:
    return len(re.findall(r"https?://|www\.", text, flags=re.IGNORECASE))

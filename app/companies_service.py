"""Entreprises (V2.3) : regrouper les contacts, typer la relation (prospect, client, assureur,
partenaire) et protéger les non-prospects de toute campagne.

Règles :
- une entreprise est reconnue par son nom « replié » : « SANLAM Maroc S.A. » = « Sanlam » ;
- le nom de l'entreprise reste recopié dans contact.company (variables, filtres, export) ;
- changer le type d'une entreprise change celui de toutes ses personnes ; passer en client,
  assureur ou partenaire arrête aussitôt leurs séquences en cours ;
- un nouveau contact rattaché à une entreprise existante en prend le type.
"""
from __future__ import annotations

import re
import unicodedata
from collections import Counter

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import CONTACT_KINDS, Company, Contact, EventLog

KIND_LABELS = {"prospect": "Prospect", "client": "Client", "insurer": "Assureur", "partner": "Partenaire"}
# Ce qui ne distingue pas deux entreprises : formes juridiques, « groupe », pays.
NOISE = {"sa", "sarl", "sarlau", "sas", "sasu", "suarl", "ste", "societe", "groupe", "group", "holding",
         "maroc", "morocco", "the", "et", "and", "cie"}


class CompanyError(ValueError):
    def __init__(self, message: str, field: str = "name", existing_id: int | None = None):
        super().__init__(message)
        self.field, self.existing_id = field, existing_id


def company_key(name: str | None) -> str:
    """« SANLAM Maroc S.A. » -> « sanlam » ; « Kapset Group » -> « kapset »."""
    if not name:
        return ""
    t = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    t = re.sub(r"\b([a-z])\.(?=[a-z]\.)", r"\1", t)  # S.A. -> sa., S.A.R.L -> sarl
    words = re.findall(r"[a-z0-9]+", t)
    kept = [w for w in words if w not in NOISE and not (len(w) == 1 and w.isalpha())]  # « S A » isolés
    return " ".join(kept or words)


def email_domain(email: str) -> str | None:
    from app.mail.inbound import is_free_mail
    d = email.rsplit("@", 1)[-1].lower() if "@" in email else ""
    return d if d and not is_free_mail(d) else None


def find(s: Session, name: str) -> Company | None:
    key = company_key(name)
    return s.scalars(select(Company).where(Company.name_key == key)).first() if key else None


def get_or_create(s: Session, name: str, kind: str = "prospect", domain: str | None = None) -> tuple[Company, bool]:
    name = " ".join(name.split())
    found = find(s, name)
    if found:
        if domain and not found.domain:
            found.domain = domain
        return found, False
    comp = Company(name=name, name_key=company_key(name), kind=kind, domain=domain, notes="")
    s.add(comp)
    s.flush()
    return comp, True


def link(s: Session, contact: Contact, kind_explicit: bool = False) -> Company | None:
    """Rattache le contact à l'entreprise de son champ « company » (créée au besoin).
    Sans type choisi pour le contact, il prend celui de l'entreprise."""
    name = (contact.company or "").strip()
    if not name:
        contact.company_id = None
        return None
    comp, created = get_or_create(s, name, contact.kind or "prospect", email_domain(contact.email))
    if contact.company_id != comp.id:
        contact.company_id = comp.id
        if not created and not kind_explicit and comp.kind != (contact.kind or "prospect"):
            contact.kind = comp.kind
    contact.company = comp.name  # orthographe unique pour toute l'entreprise
    return comp


def set_contact_kind(s: Session, contact: Contact, kind: str) -> int:
    """Change le type d'une personne ; renvoie le nombre de séquences arrêtées."""
    from app import contacts_service as cs
    if kind not in CONTACT_KINDS:
        raise CompanyError("Type inconnu.", "kind")
    if contact.kind == kind:
        return 0
    contact.kind = kind
    stopped = stop_prospection(s, contact, f"kind_{kind}") if kind != "prospect" else 0
    cs.log(s, contact, f"Type : {KIND_LABELS[kind]}" + (f" ({stopped} séquence(s) arrêtée(s))" if stopped else ""))
    return stopped


def stop_prospection(s: Session, contact: Contact, reason: str) -> int:
    """Arrête les séquences de PROSPECTION en cours du contact ; une séquence de gestion ou de
    souscription (V2.8) continue : elle s'adresse justement aux clients et assureurs."""
    from app.contacts_service import ACTIVE_ENROLLMENT
    from app.models import Campaign, Enrollment, Sequence
    n = 0
    for enr in s.scalars(select(Enrollment).join(Campaign, Campaign.id == Enrollment.campaign_id)
                         .join(Sequence, Sequence.id == Campaign.sequence_id)
                         .where(Enrollment.contact_id == contact.id, Enrollment.status.in_(ACTIVE_ENROLLMENT),
                                Sequence.category == "prospection")):
        enr.status, enr.stop_reason, enr.next_due_at = "stopped", reason, None
        n += 1
    return n


def set_kind(s: Session, comp: Company, kind: str) -> int:
    """Change le type de l'entreprise ET de toutes ses personnes."""
    if kind not in CONTACT_KINDS:
        raise CompanyError("Type inconnu.", "kind")
    comp.kind = kind
    stopped = sum(set_contact_kind(s, c, kind) for c in people(s, comp))
    s.add(EventLog(level="info", entity="company", entity_id=comp.id,
                   text=f"Entreprise « {comp.name} » : type {KIND_LABELS[kind]}"
                        + (f", {stopped} séquence(s) arrêtée(s)" if stopped else "")))
    return stopped


def rename(s: Session, comp: Company, name: str) -> None:
    name = " ".join((name or "").split())
    if not name:
        raise CompanyError("Le nom est obligatoire.")
    other = find(s, name)
    if other is not None and other.id != comp.id:
        raise CompanyError(f"« {other.name} » existe déjà : fusionnez plutôt les deux fiches.", existing_id=other.id)
    comp.name, comp.name_key = name, company_key(name)
    for c in people(s, comp):
        c.company = name


def merge(s: Session, src: Company, dst: Company) -> int:
    """Déplace les personnes de `src` vers `dst`, puis supprime `src`. Le type de `dst` s'applique."""
    if src.id == dst.id:
        raise CompanyError("Choisissez une autre entreprise.")
    moved = 0
    for c in people(s, src):
        c.company_id, c.company = dst.id, dst.name
        set_contact_kind(s, c, dst.kind)
        moved += 1
    for f in ("domain", "website", "phone", "sector"):
        if not getattr(dst, f) and getattr(src, f):
            setattr(dst, f, getattr(src, f))
    if src.notes:
        dst.notes = (dst.notes + "\n\n" if dst.notes else "") + src.notes
    s.add(EventLog(level="info", entity="company", entity_id=dst.id,
                   text=f"« {src.name} » fusionnée dans « {dst.name} » ({moved} personne(s))"))
    s.delete(src)
    return moved


def people(s: Session, comp: Company) -> list[Contact]:
    return list(s.scalars(select(Contact).where(Contact.company_id == comp.id)
                          .order_by(Contact.last_name, Contact.first_name, Contact.email)))


def counts(s: Session) -> dict[int, int]:
    return dict(s.execute(select(Contact.company_id, func.count(Contact.id))
                          .where(Contact.company_id.is_not(None)).group_by(Contact.company_id)).all())


def best_name(names: list[str]) -> str:
    """L'orthographe la plus fréquente ; à égalité, la plus longue (« Kapset Group » > « Kapset »)."""
    c = Counter(" ".join(n.split()) for n in names)
    return max(c, key=lambda n: (c[n], len(n)))

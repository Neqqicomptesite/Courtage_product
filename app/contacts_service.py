"""Requêtes et actions sur les contacts (§6.2, §9)."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import and_, delete, func, or_, select
from sqlalchemy.orm import Session

from app import suppression
from app.models import Campaign, Company, Contact, Enrollment, EventLog, Message

# La colonne « Fiabilité » du fichier est du texte libre (« Bonne (Limadata, via LinkedIn) »…).
# On classe d'après le début du texte. L'ordre compte : « À vérifier » avant le reste.
RELIABILITY_CATEGORIES = ["Bonne", "Moyenne", "À vérifier", "Personnelle", "Générique"]
OTHER = "Autre"

STATUS_LABELS = {
    "active": "Actif",
    "replied": "A répondu",
    "bounced": "Rebond",
    "unsubscribed": "Désinscrit",
    "do_not_contact": "Ne plus contacter",
}
ACTIVE_ENROLLMENT = ("scheduled", "sending", "waiting", "error", "needs_review")


def reliability_category(text: str | None) -> str:
    t = (text or "").strip().lower()
    for cat in RELIABILITY_CATEGORIES:
        if t.startswith(cat.lower()) or (cat == "À vérifier" and t.startswith("a vérifier")):
            return cat
    return OTHER


def _reliability_clause(category: str):
    if category == OTHER:
        # « Autre » = vide, OU ne commence par AUCUNE des catégories (d'où le and_).
        return or_(Contact.email_reliability.is_(None),
                   and_(*[~Contact.email_reliability.like(f"{c}%") for c in RELIABILITY_CATEGORIES]))
    # SQLite ne compare sans casse que les lettres sans accent ; le fichier écrit toujours
    # « Bonne », « À vérifier »… avec la même majuscule, on compare donc le début exact.
    return Contact.email_reliability.like(f"{category}%")


@dataclass
class ContactFilters:
    q: str = ""
    target_segment: str = ""
    sector_family: str = ""
    sequence_code: str = ""
    wave: str = ""
    reliability: str = ""
    status: str = ""
    campaign_id: str = ""
    kind: str = ""
    company_id: str = ""
    department: str = ""   # V2.18 : filtres de l'onglet Assureurs
    seniority: str = ""
    owner: str = ""        # V3 : "me" (mes prospects), "none" (non assignés) ou un numéro d'employé
    no_reply_of: str = ""  # V3.5 : sont allés au bout de cette campagne sans répondre
    list_id: str = ""      # V3.6 : membres de cette liste (visible par l'employé)

    @classmethod
    def from_query(cls, params) -> "ContactFilters":
        return cls(**{k: (params.get(k) or "").strip() for k in cls.__dataclass_fields__})

    @property
    def active(self) -> bool:
        return any(getattr(self, k) for k in self.__dataclass_fields__)


def filtered_query(f: ContactFilters):
    stmt = select(Contact)
    for col in ("target_segment", "sector_family", "sequence_code", "wave"):
        if getattr(f, col):
            stmt = stmt.where(getattr(Contact, col) == getattr(f, col))
    if f.status:
        stmt = stmt.where(Contact.global_status == f.status)
    if f.kind:
        stmt = stmt.where(Contact.kind == f.kind)
    if f.company_id.isdigit():
        stmt = stmt.where(Contact.company_id == int(f.company_id))
    for col in ("department", "seniority"):
        if getattr(f, col):
            stmt = stmt.where(getattr(Contact, col) == getattr(f, col))
    if f.owner == "me":
        from app.current import user_id
        stmt = stmt.where(Contact.owner_id == user_id())
    elif f.owner == "none":
        stmt = stmt.where(Contact.owner_id.is_(None))
    elif f.owner.isdigit():
        stmt = stmt.where(Contact.owner_id == int(f.owner))
    if f.reliability:
        stmt = stmt.where(_reliability_clause(f.reliability))
    if f.campaign_id.isdigit():
        stmt = stmt.where(Contact.id.in_(
            select(Enrollment.contact_id).where(Enrollment.campaign_id == int(f.campaign_id))))
    if f.list_id.isdigit():
        from app.models import ContactList, ContactListMember
        visible = select(ContactList.id).where(ContactList.id == int(f.list_id))  # filtre « ses listes ou partagées »
        stmt = stmt.where(Contact.id.in_(select(ContactListMember.contact_id).where(ContactListMember.list_id.in_(visible))))
    if f.no_reply_of.isdigit():
        stmt = stmt.where(Contact.id.in_(
            select(Enrollment.contact_id).where(Enrollment.campaign_id == int(f.no_reply_of),
                                                Enrollment.status == "completed")))
    if f.q:
        like = f"%{f.q}%"
        stmt = stmt.where(or_(Contact.email.ilike(like), Contact.first_name.ilike(like),
                              Contact.last_name.ilike(like), Contact.company.ilike(like),
                              Contact.job_title.ilike(like)))
    return stmt.order_by(Contact.company, Contact.last_name)


def filter_options(session: Session) -> dict[str, list]:
    def distinct(col):
        return [v for v in session.scalars(select(col).distinct().where(col.is_not(None)).order_by(col))]
    return {
        "target_segment": distinct(Contact.target_segment),
        "sector_family": distinct(Contact.sector_family),
        "sequence_code": distinct(Contact.sequence_code),
        "wave": distinct(Contact.wave),
        "reliability": RELIABILITY_CATEGORIES + [OTHER],
        "status": list(STATUS_LABELS.items()),
        "campaigns": [(c.id, c.name) for c in session.scalars(select(Campaign).order_by(Campaign.name))],
        "department": distinct(Contact.department),
        "seniority": distinct(Contact.seniority),
        # V2.18 : entreprises qui ont des contacts, par type de contact (filtre « Compagnie » / « Entreprise »)
        "companies_by_kind": _companies_by_kind(session),
    }


def _companies_by_kind(session: Session) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    rows = session.execute(select(Contact.kind, Company.id, Company.name).join(Company, Company.id == Contact.company_id)
                           .distinct().order_by(Company.name))
    for kind, cid, name in rows:
        out.setdefault(kind, []).append({"value": str(cid), "label": name})
    return out


def count_all(session: Session) -> int:
    return session.scalar(select(func.count(Contact.id))) or 0


# -------------------------------------------------------------- fiche contact

@dataclass
class TimelineItem:
    ts: datetime
    kind: str      # "out" | "in" | "event"
    title: str
    detail: str = ""


def timeline(session: Session, contact: Contact) -> list[TimelineItem]:
    items: list[TimelineItem] = []
    for m in session.scalars(select(Message).where(Message.contact_id == contact.id)):
        if m.direction == "out":
            title = (f"Email envoyé (étape {m.step_position or '?'})" if m.enrollment_id or m.step_position
                     else "Email écrit depuis la boîte mail")  # V2.4 : email écrit à la main
            items.append(TimelineItem(m.sent_at or contact.created_at, "out", title, m.subject))
        else:
            items.append(TimelineItem(m.received_at or contact.created_at, "in",
                                      f"Email reçu ({m.kind or 'réponse'})", m.subject))
    for e in session.scalars(select(EventLog).where(EventLog.entity == "contact",
                                                    EventLog.entity_id == contact.id)):
        items.append(TimelineItem(e.ts, "event", e.text))
    items.append(TimelineItem(contact.created_at, "event", f"Contact créé – source : {contact.source or '—'}"))
    return sorted(items, key=lambda i: i.ts, reverse=True)


def enrollments_of(session: Session, contact: Contact) -> list[tuple[Enrollment, Campaign]]:
    return list(session.execute(
        select(Enrollment, Campaign).join(Campaign, Campaign.id == Enrollment.campaign_id)
        .where(Enrollment.contact_id == contact.id).order_by(Enrollment.created_at)))


def log(session: Session, contact: Contact, text: str, level: str = "info") -> None:
    session.add(EventLog(level=level, entity="contact", entity_id=contact.id, text=text))


def stop_active_enrollments(session: Session, contact: Contact, reason: str) -> int:
    n = 0
    for enr in session.scalars(select(Enrollment).where(Enrollment.contact_id == contact.id,
                                                       Enrollment.status.in_(ACTIVE_ENROLLMENT))):
        enr.status, enr.stop_reason, enr.next_due_at = "stopped", reason, None
        n += 1
    return n


def set_do_not_contact(session: Session, contact: Contact) -> None:
    contact.global_status = "do_not_contact"
    n = stop_active_enrollments(session, contact, "manual_do_not_contact")
    log(session, contact, f"Statut → Ne plus contacter ({n} séquence(s) arrêtée(s))")


class ReactivationRefused(Exception):
    pass


def reactivate(session: Session, contact: Contact) -> None:
    """Un contact désinscrit (STOP) ou présent dans la liste d'exclusion ne peut pas être
    réactivé : la désinscription est définitive (§9)."""
    if contact.global_status == "unsubscribed":
        raise ReactivationRefused("Ce contact s'est désinscrit (STOP) : la désinscription est définitive.")
    if suppression.is_suppressed_db(session, contact.email):
        raise ReactivationRefused("Cette adresse (ou son domaine) est dans la liste d'exclusion. "
                                  "Retirez-la d'abord de la liste si c'était une erreur.")
    old = contact.global_status
    contact.global_status = "active"
    log(session, contact, f"Statut → Actif (était : {STATUS_LABELS.get(old, old)})")


def remove_from_campaign(session: Session, contact: Contact, enrollment_id: int) -> bool:
    enr = session.get(Enrollment, enrollment_id)
    if enr is None or enr.contact_id != contact.id or enr.status not in ACTIVE_ENROLLMENT:
        return False
    enr.status, enr.stop_reason, enr.next_due_at = "stopped", "manual_removed", None
    log(session, contact, f"Retiré de la campagne n°{enr.campaign_id}")
    return True


def erase(session: Session, contact: Contact) -> None:
    """Droit d'effacement (§9) : supprime le contact, ses emails et son historique,
    et ne garde que l'empreinte de son adresse dans la liste d'exclusion."""
    suppression.add(session, suppression.email_hash(contact.email), "Données effacées (droit d'effacement)")
    session.execute(delete(Message).where(Message.contact_id == contact.id))
    session.execute(delete(EventLog).where(EventLog.entity == "contact", EventLog.entity_id == contact.id))
    session.execute(delete(Enrollment).where(Enrollment.contact_id == contact.id))
    session.delete(contact)
    # Aucune donnée personnelle dans ce journal : seulement le numéro interne.
    session.add(EventLog(level="warning", entity="contact", entity_id=None,
                         text=f"Contact n°{contact.id} effacé définitivement (droit d'effacement)"))


# ------------------------------------------------- saisie et modification à la main (V2.2)

EDITABLE_FIELDS = ("first_name", "last_name", "email", "job_title", "company", "phone", "website", "linkedin_url",
                   "sector", "target_segment", "sector_family", "size_bucket", "wave", "email_reliability",
                   "department", "seniority")
FIELD_LABELS = {"first_name": "prénom", "last_name": "nom", "email": "email", "job_title": "poste",
                "company": "entreprise", "phone": "téléphone", "website": "site web", "linkedin_url": "LinkedIn",
                "sector": "secteur", "target_segment": "cible", "sector_family": "famille de secteur",
                "size_bucket": "taille", "wave": "vague", "email_reliability": "fiabilité",
                "sequence_code": "code séquence", "kind": "type", "department": "service", "seniority": "niveau"}
DEPARTMENT_LABELS = {"souscription": "Souscription", "gestion": "Gestion", "production": "Production",
                     "maritime_transport": "Maritime / transport", "autre": "Autre"}
SENIORITY_LABELS = {"directeur": "Directeur de département", "senior": "Senior", "junior": "Junior"}


class ContactInvalid(ValueError):
    """Erreurs par champ, affichées sous chaque case du formulaire."""

    def __init__(self, errors: dict[str, str], existing_id: int | None = None):
        super().__init__(" ".join(errors.values()))
        self.errors, self.existing_id = errors, existing_id


def _clean(data: dict) -> dict:
    out = {}
    for k in EDITABLE_FIELDS:
        if k in data:
            v = data[k]
            v = str(v).strip() if v is not None else ""
            out[k] = v or None
    if out.get("email"):
        out["email"] = out["email"].lower()
    if out.get("department") and out["department"] not in DEPARTMENT_LABELS:
        raise ContactInvalid({"department": "Service inconnu."})
    if out.get("seniority") and out["seniority"] not in SENIORITY_LABELS:
        raise ContactInvalid({"seniority": "Niveau inconnu."})
    return out


def _check_email(session: Session, email: str | None, current: Contact | None) -> None:
    from app.importer import EMAIL_RE  # import local : importer dépend de ce module via suppression
    if not email:
        raise ContactInvalid({"email": "L'email est obligatoire."})
    if not EMAIL_RE.match(email):
        raise ContactInvalid({"email": "Adresse email invalide."})
    other = session.scalars(select(Contact).where(Contact.email == email)).first()
    if other is not None and other is not current:
        raise ContactInvalid({"email": "Un contact existe déjà avec cet email."}, existing_id=other.id)
    if suppression.email_hash(email) in suppression.suppressed_keys(session):
        raise ContactInvalid({"email": "Cette personne a été effacée à sa demande : elle ne peut pas être recréée."})


def _apply(contact: Contact, values: dict) -> list[str]:
    from app import vocab
    changed = []
    for k, v in values.items():
        if getattr(contact, k) != v:
            setattr(contact, k, v)
            changed.append(k)
    # Le code séquence suit la cible et le secteur quand ils sont reconnus (FIN + BTP -> FIN-BTP).
    derived = vocab.sequence_code(contact.target_segment, contact.sector_family)
    if derived and derived != contact.sequence_code:
        contact.sequence_code = derived
        changed.append("sequence_code")
    return changed


def _kind(data: dict) -> str | None:
    from app.models import CONTACT_KINDS
    k = (data.get("kind") or "").strip()
    if k and k not in CONTACT_KINDS:
        raise ContactInvalid({"kind": "Type inconnu."})
    return k or None


def create_contact(session: Session, data: dict, source: str) -> tuple[Contact, list[str]]:
    """Crée un contact saisi à la main. Renvoie (contact, avertissements)."""
    from app import companies_service
    values = _clean(data)
    kind = _kind(data)
    _check_email(session, values.get("email"), None)
    contact = Contact(email=values["email"], source=source, custom={}, notes=(data.get("notes") or "").strip(),
                      kind=kind or "prospect")
    session.add(contact)
    _apply(contact, values)
    if data.get("sequence_code") and not contact.sequence_code:
        contact.sequence_code = str(data["sequence_code"]).strip().upper() or None
    session.flush()
    companies_service.link(session, contact, kind_explicit=kind is not None)
    warnings = []
    if suppression.is_suppressed_db(session, contact.email):
        warnings.append("Adresse sur la liste d'exclusion : aucun email ne lui sera envoyé.")
    # pas de ligne d'historique ici : la fiche affiche déjà « Contact créé – source : Saisie manuelle… »
    return contact, warnings


def last_bounce(session: Session, contact: Contact):
    """V3.5 : date du dernier rebond définitif reçu pour ce contact (dans n'importe quelle boîte)."""
    return session.scalar(select(func.max(Message.received_at)).where(
        Message.contact_id == contact.id, Message.kind == "bounce_hard").execution_options(oddo_all=True))


def new_address(session: Session, old: Contact, email: str) -> Contact:
    """V3.5 : l'adresse a rebondi. Une nouvelle fiche reprend tout avec la bonne adresse ; l'ancienne
    reste « Rebond » avec son historique (on ne change pas l'adresse d'emails déjà échangés)."""
    data = {k: getattr(old, k) for k in EDITABLE_FIELDS if k not in ("email", "email_reliability")}
    data.update(email=email, kind=old.kind)
    new, _ = create_contact(session, data, f"Nouvelle adresse : l'ancienne ({old.email}) a rebondi")
    new.custom = dict(old.custom or {})
    new.notes = old.notes or ""
    new.owner_id = old.owner_id
    if old.sequence_code:
        new.sequence_code = old.sequence_code
    log(session, old, f"Nouvelle adresse enregistrée sur une nouvelle fiche : {new.email}")
    return new


def update_contact(session: Session, contact: Contact, data: dict) -> list[str]:
    """Modifie les champs fournis. Renvoie la liste des champs changés."""
    values = _clean(data)
    if "email" in values and values["email"] != contact.email:
        _check_email(session, values["email"], contact)
        has_messages = session.scalars(select(Message.id).where(Message.contact_id == contact.id)).first()
        if has_messages:
            raise ContactInvalid({"email": "Des emails ont déjà été échangés avec cette adresse : créez plutôt un nouveau contact."})
    from app import companies_service
    kind = _kind(data)
    changed = _apply(contact, values)
    if "company" in changed:
        companies_service.link(session, contact, kind_explicit=kind is not None)
    if kind and kind != contact.kind:
        companies_service.set_contact_kind(session, contact, kind)
        changed.append("kind")
    if "custom" in data and isinstance(data["custom"], dict):
        custom = dict(contact.custom or {})
        for k, v in data["custom"].items():
            v = (str(v) if v is not None else "").strip()
            if v and custom.get(k) != v:
                custom[k] = v
                changed.append(k)
            elif not v and k in custom:
                del custom[k]
                changed.append(k)
        contact.custom = custom  # nouveau dict : SQLAlchemy ne voit pas une modification « sur place »
    if changed:
        labels = sorted({FIELD_LABELS.get(k, k.replace("_", " ")) for k in changed})
        log(session, contact, "Fiche modifiée : " + ", ".join(labels))
    return changed

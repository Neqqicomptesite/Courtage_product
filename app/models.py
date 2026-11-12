"""Modèle de données (cahier des charges §5).

Toutes les tables sont créées dès M1, même celles qui ne serviront qu'aux
jalons suivants : cela évite de casser la base à chaque jalon.
Écarts par rapport au §5 (voir DECISIONS.md) :
- message.references -> colonne `references_header` (REFERENCES est un mot réservé SQL) ;
- message.sent_at / received_at : deux colonnes distinctes ;
- enrollment : ajout de updated_at, attempts, last_error (nécessaires au moteur d'envoi).
"""
from datetime import date, datetime

from sqlalchemy import (
    JSON, Boolean, CheckConstraint, Date, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, validates

from app.db import Base, UTCDateTime
from app.timeutil import utcnow

# Valeurs autorisées. Elles sont aussi vérifiées par la base (CheckConstraint) :
# une faute de frappe dans le code provoquera une erreur immédiate au lieu
# d'un statut fantôme que personne ne remarque.
CONTACT_STATUSES = ("active", "replied", "bounced", "unsubscribed", "do_not_contact")
# Type de contact (V2.3) : seuls les prospects peuvent entrer dans une campagne de PROSPECTION.
CONTACT_KINDS = ("prospect", "client", "insurer", "partner")
# V2.8 : type de séquence. Seule la prospection est réservée aux prospects (et porte la ligne STOP).
SEQUENCE_CATEGORIES = ("prospection", "gestion", "souscription")
# V2.8 : service et niveau d'une personne (surtout chez les assureurs)
DEPARTMENTS = ("souscription", "gestion", "production", "maritime_transport", "autre")
SENIORITIES = ("junior", "senior", "directeur")
REMINDER_KINDS = ("call", "email", "quote", "meeting", "renewal", "other")
CAMPAIGN_STATUSES = ("draft", "active", "paused", "finished")
ENROLLMENT_STATUSES = ("scheduled", "sending", "waiting", "replied", "bounced",
                       "unsubscribed", "stopped", "completed", "error", "needs_review")
# kind ne concerne que les messages reçus (NULL pour les messages envoyés).
MESSAGE_KINDS = ("reply","auto_reply", "bounce_hard", "bounce_soft", "unsubscribe", "unmatched")
CLASSIFICATIONS = ("interested", "later", "not_interested", "out_of_office", "wrong_contact", "unsubscribe")
SMTP_SECURITY = ("ssl", "starttls")


def _in(col: str, values: tuple[str, ...], nullable: bool = False) -> CheckConstraint:
    allowed = ", ".join(f"'{v}'" for v in values)
    expr = f"{col} IN ({allowed})"
    if nullable:
        expr = f"{col} IS NULL OR {expr}"
    return CheckConstraint(expr, name=f"ck_{col}")


class AppUser(Base):
    """V3 : un employé (compte de connexion Supabase). Rôle « admin » : gère les comptes."""
    __tablename__ = "app_user"
    __table_args__ = (_in("role", ("admin", "user")),)

    id: Mapped[int] = mapped_column(primary_key=True)
    auth_id: Mapped[str | None] = mapped_column(String(64), unique=True)  # identifiant Supabase (sub du jeton)
    email: Mapped[str] = mapped_column(String(254), unique=True)          # en minuscules
    full_name: Mapped[str] = mapped_column(String(120), default="")
    role: Mapped[str] = mapped_column(String(10), default="user", server_default="user")
    active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="1")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    last_seen_at: Mapped[datetime | None] = mapped_column(UTCDateTime)


class Mailbox(Base):
    __tablename__ = "mailbox"
    __table_args__ = (_in("smtp_security", SMTP_SECURITY),)

    id: Mapped[int] = mapped_column(primary_key=True)
    display_name: Mapped[str] = mapped_column(String(120))
    email: Mapped[str] = mapped_column(String(254), unique=True)
    smtp_host: Mapped[str] = mapped_column(String(255), default="")
    smtp_port: Mapped[int] = mapped_column(Integer, default=465)
    smtp_security: Mapped[str] = mapped_column(String(10), default="ssl")
    imap_host: Mapped[str] = mapped_column(String(255), default="")
    imap_port: Mapped[int] = mapped_column(Integer, default=993)
    username: Mapped[str] = mapped_column(String(254), default="")
    # Le mot de passe n'est PAS ici : il est dans le Gestionnaire d'identification Windows.
    sent_folder: Mapped[str | None] = mapped_column(String(255))
    watched_folders: Mapped[list] = mapped_column(JSON, default=lambda: ["INBOX"])
    signature: Mapped[str] = mapped_column(Text, default="")
    daily_cap: Mapped[int] = mapped_column(Integer, default=25)
    hourly_cap: Mapped[int] = mapped_column(Integer, default=10)
    min_gap_s: Mapped[int] = mapped_column(Integer, default=90)
    max_gap_s: Mapped[int] = mapped_column(Integer, default=240)
    # V3 : la boîte de quel employé (une par personne ; vide en mode poste unique)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("app_user.id", ondelete="SET NULL"), unique=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class Company(Base):
    """Entreprise (V2.3). Le nom est aussi recopié dans contact.company, utilisé par les
    variables des emails ({{ entreprise }}), les filtres et l'export."""
    __tablename__ = "company"

    @validates("website")
    def _safe_links(self, _key, value):
        return safe_web_url(value)
    __table_args__ = (_in("kind", CONTACT_KINDS),)

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    name_key: Mapped[str] = mapped_column(String(255), unique=True)  # nom « replié » : SANLAM Maroc = Sanlam
    kind: Mapped[str] = mapped_column(String(12), default="prospect", server_default="prospect", index=True)
    domain: Mapped[str | None] = mapped_column(String(255), index=True)
    website: Mapped[str | None] = mapped_column(String(255))
    phone: Mapped[str | None] = mapped_column(String(60))
    sector: Mapped[str | None] = mapped_column(String(255))
    notes: Mapped[str] = mapped_column(Text, default="", server_default="")
    logo: Mapped[str | None] = mapped_column(String(120))  # V2.8 : fichier dans data/logos
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)


class Contact(Base):
    __tablename__ = "contact"

    @validates("website", "linkedin_url")
    def _safe_links(self, _key, value):
        return safe_web_url(value)

    __table_args__ = (_in("global_status", CONTACT_STATUSES), _in("kind", CONTACT_KINDS))

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(254), unique=True)  # toujours en minuscules
    first_name: Mapped[str | None] = mapped_column(String(120))
    last_name: Mapped[str | None] = mapped_column(String(120))
    company: Mapped[str | None] = mapped_column(String(255))
    job_title: Mapped[str | None] = mapped_column(String(255))
    sector: Mapped[str | None] = mapped_column(String(255))
    sector_family: Mapped[str | None] = mapped_column(String(120))
    target_segment: Mapped[str | None] = mapped_column(String(120))
    sequence_code: Mapped[str | None] = mapped_column(String(30), index=True)
    size_bucket: Mapped[str | None] = mapped_column(String(60))
    wave: Mapped[str | None] = mapped_column(String(60))
    lot_number: Mapped[int | None] = mapped_column(Integer, index=True)  # V3.7 : n° de l'import / de la recherche
    email_reliability: Mapped[str | None] = mapped_column(Text)
    phone: Mapped[str | None] = mapped_column(String(60))
    website: Mapped[str | None] = mapped_column(String(255))
    linkedin_url: Mapped[str | None] = mapped_column(String(500))
    source: Mapped[str | None] = mapped_column(String(255))
    custom: Mapped[dict] = mapped_column(JSON, default=dict)
    global_status: Mapped[str] = mapped_column(String(20), default="active", index=True)
    kind: Mapped[str] = mapped_column(String(12), default="prospect", server_default="prospect", index=True)
    company_id: Mapped[int | None] = mapped_column(ForeignKey("company.id", ondelete="SET NULL"), index=True)
    department: Mapped[str | None] = mapped_column(String(20))   # V2.8 : souscription, gestion…
    seniority: Mapped[str | None] = mapped_column(String(12))    # V2.8 : junior, senior, directeur
    notes: Mapped[str] = mapped_column(Text, default="")
    # V3 : « suivi par » (repère : premier qui lui a écrit, ou choisi par l'admin) ; ne bloque aucun envoi
    owner_id: Mapped[int | None] = mapped_column(ForeignKey("app_user.id", ondelete="SET NULL"), index=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)


class Suppression(Base):
    """Liste d'exclusion permanente : un email, ou un domaine entier (ex. « @exemple.ma »)."""
    __tablename__ = "suppression"

    id: Mapped[int] = mapped_column(primary_key=True)
    email_or_domain: Mapped[str] = mapped_column(String(254), unique=True)
    reason: Mapped[str] = mapped_column(String(255), default="")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class ContentBlock(Base):
    __tablename__ = "content_block"
    __table_args__ = (UniqueConstraint("kind", "key"), _in("kind", ("target", "sector")))

    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(10))
    key: Mapped[str] = mapped_column(String(20))
    body: Mapped[str] = mapped_column(Text, default="")
    label: Mapped[str | None] = mapped_column(String(120))  # V2.9 : fonction / secteur ajouté par Omar
    variant_of: Mapped[str | None] = mapped_column(String(20))  # V3.4 : variante d'un texte (ex. FIN2 → FIN)


class Sequence(Base):
    __tablename__ = "sequence"
    __table_args__ = (_in("category", SEQUENCE_CATEGORIES),)

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    category: Mapped[str] = mapped_column(String(15), default="prospection", server_default="prospection")
    branch: Mapped[str | None] = mapped_column(String(40))  # V3 : branche (cotations : flotte, AT…)
    # V3 : modèle personnel d'un employé (vide = modèle commun à l'équipe)
    owner_id: Mapped[int | None] = mapped_column(ForeignKey("app_user.id", ondelete="SET NULL"), index=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class Step(Base):
    __tablename__ = "step"
    __table_args__ = (UniqueConstraint("sequence_id", "position"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    sequence_id: Mapped[int] = mapped_column(ForeignKey("sequence.id", ondelete="CASCADE"))
    position: Mapped[int] = mapped_column(Integer)  # 1, 2, 3...
    delay_days: Mapped[int] = mapped_column(Integer, default=0)
    business_days: Mapped[bool] = mapped_column(Boolean, default=True)
    # V2.5, « relance à un jour précis » : jour de la semaine (0 = lundi) et heure locale « HH:MM »
    weekday: Mapped[int | None] = mapped_column(Integer)
    send_time: Mapped[str | None] = mapped_column(String(5))
    same_thread: Mapped[bool] = mapped_column(Boolean, default=True)
    body_template: Mapped[str] = mapped_column(Text, default="")


class StepVariant(Base):
    """Objet de l'email. L'étape 1 peut en avoir deux (A/B) ; les relances n'en ont pas
    besoin quand elles répondent dans le même fil (« Re: »)."""
    __tablename__ = "step_variant"
    __table_args__ = (UniqueConstraint("step_id", "label"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    step_id: Mapped[int] = mapped_column(ForeignKey("step.id", ondelete="CASCADE"))
    label: Mapped[str] = mapped_column(String(5))  # "A" ou "B"
    subject_template: Mapped[str] = mapped_column(Text, default="")


class Campaign(Base):
    __tablename__ = "campaign"
    __table_args__ = (_in("status", CAMPAIGN_STATUSES),)

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    mailbox_id: Mapped[int] = mapped_column(ForeignKey("mailbox.id"))
    sequence_id: Mapped[int] = mapped_column(ForeignKey("sequence.id"))
    status: Mapped[str] = mapped_column(String(10), default="draft")
    filters: Mapped[dict] = mapped_column(JSON, default=dict)
    stop_on_domain_reply: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    activated_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    start_at: Mapped[datetime | None] = mapped_column(UTCDateTime)  # V2.5 : démarrage planifié (sinon : tout de suite)
    # V2.9 : campagne « à l'unité » d'une séquence (envois lancés depuis la boîte mail ou une fiche)
    direct: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    # V3.4 : textes de la campagne. {"target": {"FIN": "FIN2" | ["FIN", "FIN2"]}, "sector": {...}} :
    # remplace le texte de la fiche du contact (une liste = partage A/B entre les personnes).
    block_map: Mapped[dict | None] = mapped_column(JSON)


class Enrollment(Base):
    """Un contact inscrit dans une campagne : où il en est de la séquence."""
    __tablename__ = "enrollment"
    # V2.23 (migration 0009) : plus de contrainte (campagne, contact) unique : une séquence de gestion
    # ou de souscription peut partir plusieurs fois à la même personne (un envoi par dossier).
    # La règle « une seule fois » reste appliquée en code pour la prospection et les campagnes de groupe.
    __table_args__ = (Index("ix_enrollment_campaign_contact", "campaign_id", "contact_id"),
                      _in("status", ENROLLMENT_STATUSES))

    id: Mapped[int] = mapped_column(primary_key=True)
    campaign_id: Mapped[int] = mapped_column(ForeignKey("campaign.id", ondelete="CASCADE"))
    contact_id: Mapped[int] = mapped_column(ForeignKey("contact.id", ondelete="CASCADE"))
    variant_label: Mapped[str | None] = mapped_column(String(5))
    current_step: Mapped[int] = mapped_column(Integer, default=1)  # prochaine étape à envoyer
    next_due_at: Mapped[datetime | None] = mapped_column(UTCDateTime, index=True)
    status: Mapped[str] = mapped_column(String(15), default="scheduled", index=True)
    stop_reason: Mapped[str | None] = mapped_column(String(50))
    thread_root_message_id: Mapped[str | None] = mapped_column(String(255))
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(Text)
    # V2.9 : emails personnalisés pour ce contact {"1": {"subject": …, "body": …}}
    overrides: Mapped[dict | None] = mapped_column(JSON)
    block_code: Mapped[str | None] = mapped_column(String(30))  # V3.4 : textes envoyés (ex. FIN2-IND), fixés au 1er email
    # V2.24 (migration 0010) : n'envoyer que les N premiers emails (NULL = toute la séquence)
    max_steps: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)


class Message(Base):
    __tablename__ = "message"
    __table_args__ = (_in("direction", ("out", "in")),
                      _in("kind", MESSAGE_KINDS, nullable=True),
                      _in("classification", CLASSIFICATIONS, nullable=True))

    id: Mapped[int] = mapped_column(primary_key=True)
    enrollment_id: Mapped[int | None] = mapped_column(ForeignKey("enrollment.id", ondelete="SET NULL"))
    contact_id: Mapped[int | None] = mapped_column(ForeignKey("contact.id", ondelete="SET NULL"))
    # V3 : la boîte (donc l'employé) qui a envoyé ou reçu ce message
    mailbox_id: Mapped[int | None] = mapped_column(ForeignKey("mailbox.id", ondelete="SET NULL"), index=True)
    direction: Mapped[str] = mapped_column(String(3))
    message_id: Mapped[str | None] = mapped_column(String(255), index=True)
    # Destinataire RÉEL de l'email parti (en mode test : l'adresse d'Omar, pas celle du contact).
    to_email: Mapped[str | None] = mapped_column(String(254))
    test_mode: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    in_reply_to: Mapped[str | None] = mapped_column(String(255))
    references_header: Mapped[str | None] = mapped_column(Text)
    subject: Mapped[str] = mapped_column(Text, default="")
    body_text: Mapped[str] = mapped_column(Text, default="")
    body_full: Mapped[str | None] = mapped_column(Text)  # texte complet, citation comprise
    step_position: Mapped[int | None] = mapped_column(Integer)
    sent_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    received_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    imap_folder: Mapped[str | None] = mapped_column(String(255))
    imap_uid: Mapped[int | None] = mapped_column(Integer)
    kind: Mapped[str | None] = mapped_column(String(15))
    classification: Mapped[str | None] = mapped_column(String(20))
    return_date: Mapped[str | None] = mapped_column(String(60))           # absence : date de retour lue
    note: Mapped[str | None] = mapped_column(Text)                         # note d'Omar sur la réponse
    callback_on: Mapped[date | None] = mapped_column(Date)                 # « À rappeler plus tard » : quand
    suggested_contact_id: Mapped[int | None] = mapped_column(Integer)      # réponse non rattachée : piste
    classified_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    seen_at: Mapped[datetime | None] = mapped_column(UTCDateTime)  # « Marquer comme lu » sans classer (V3.3.2)
    attachments: Mapped[list | None] = mapped_column(JSON)  # V2.8 : noms des pièces jointes envoyées
    raw_headers: Mapped[str | None] = mapped_column(Text)


class ImapState(Base):
    """Où on s'est arrêté dans chaque dossier IMAP (pour ne lire que les nouveaux messages)."""
    __tablename__ = "imap_state"

    mailbox_id: Mapped[int] = mapped_column(ForeignKey("mailbox.id", ondelete="CASCADE"), primary_key=True)
    folder: Mapped[str] = mapped_column(String(255), primary_key=True)
    uidvalidity: Mapped[int | None] = mapped_column(Integer)
    last_uid: Mapped[int] = mapped_column(Integer, default=0)


def safe_web_url(value: str | None) -> str | None:
    """V3 (revue externe, point 6) : un lien de site ou de profil n'est gardé que s'il est en
    http(s). « exemple.ma » devient « https://exemple.ma » ; « javascript:… » ou tout autre
    schéma est refusé (il deviendrait un lien piégé, cliquable par tous les collègues)."""
    if value is None:
        return None
    v = value.strip()
    if not v:
        return None
    low = v.lower()
    if low.startswith(("http://", "https://")):
        return v
    if ":" in v.split("/")[0] or low.startswith("//"):
        return None  # autre schéma (javascript:, data:, vbscript:…) : refusé
    return "https://" + v


def _current_user() -> int | None:
    from app.current import user_id
    return user_id()


class EventLog(Base):
    __tablename__ = "event_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    ts: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, index=True)
    level: Mapped[str] = mapped_column(String(10), default="info")
    entity: Mapped[str | None] = mapped_column(String(30))
    entity_id: Mapped[int | None] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)
    # V3 : l'employé concerné (rempli tout seul d'après l'employé « en cours »)
    user_id: Mapped[int | None] = mapped_column(Integer, index=True, default=lambda: _current_user())


class Secret(Base):
    """V3 (serveur) : mots de passe des boîtes mail, chiffrés (clé ODDO_SECRET_KEY du serveur).
    Sur un poste unique, ils restent dans le Gestionnaire d'identification Windows."""
    __tablename__ = "secret"

    service: Mapped[str] = mapped_column(String(100), primary_key=True)
    account: Mapped[str] = mapped_column(String(254), primary_key=True)
    value: Mapped[str] = mapped_column(Text)  # chiffré (Fernet)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)


class Setting(Base):
    """Réglages globaux, stockés en JSON (voir app/settings_store.py pour les valeurs par défaut)."""
    __tablename__ = "setting"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[str] = mapped_column(Text)


class Attachment(Base):
    """Pièce jointe (V2.8), rangée dans data/attachments/<token>/<nom>. Jamais supprimée :
    l'historique des emails envoyés y fait référence."""
    __tablename__ = "attachment"

    id: Mapped[int] = mapped_column(primary_key=True)
    token: Mapped[str] = mapped_column(String(40), unique=True)
    filename: Mapped[str] = mapped_column(String(255))
    content_type: Mapped[str] = mapped_column(String(120), default="application/octet-stream")
    size: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class StepAttachment(Base):
    """Pièces jointes d'une étape de séquence (V2.8)."""
    __tablename__ = "step_attachment"
    __table_args__ = (UniqueConstraint("step_id", "attachment_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    step_id: Mapped[int] = mapped_column(ForeignKey("step.id", ondelete="CASCADE"), index=True)
    attachment_id: Mapped[int] = mapped_column(ForeignKey("attachment.id", ondelete="CASCADE"))


class Reminder(Base):
    """Rappel de l'agenda (V2.8) : « rappeler dans 3 jours », « relancer le devis »…"""
    __tablename__ = "reminder"
    __table_args__ = (_in("kind", REMINDER_KINDS),)

    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(10), default="other")
    title: Mapped[str] = mapped_column(String(255))
    notes: Mapped[str] = mapped_column(Text, default="", server_default="")
    due_on: Mapped[date] = mapped_column(Date, index=True)
    due_time: Mapped[str | None] = mapped_column(String(5))
    contact_id: Mapped[int | None] = mapped_column(ForeignKey("contact.id", ondelete="CASCADE"), index=True)
    company_id: Mapped[int | None] = mapped_column(ForeignKey("company.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("app_user.id", ondelete="CASCADE"), index=True)  # V3
    # Dossiers de cotation : rappel lié à un dossier de cotation (relance d'une compagnie)
    quote_case_id: Mapped[int | None] = mapped_column(ForeignKey("quote_case.id", ondelete="CASCADE"), index=True)
    # Contrats : rappel de préavis avant l'échéance d'un contrat (créé par app/contracts.py)
    contract_id: Mapped[int | None] = mapped_column(ForeignKey("contract.id", ondelete="CASCADE"), index=True)
    done_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


# ---------------------------------------------------------------------------------------------
# Dossiers de cotation. Visibles par toute l'équipe du cabinet (un dossier se
# reprend facilement par un collègue), avec un responsable. Toutes ces tables portent org_id.

QUOTE_STAGES = ("new", "info", "consulting", "partial", "offers", "proposed", "won", "lost")
QUOTE_INSURER_STATUSES = ("to_send", "sent", "reminded", "replied", "offer", "renegotiate", "declined")
QUOTE_EVENT_KINDS = ("created", "stage", "note", "fields", "email_out", "email_in", "file", "insurer", "edit")
QUOTE_FILE_KINDS = ("client", "current", "offer", "other")


def _current_org() -> int:
    from app.current import org_id
    return org_id()


class QuoteCase(Base):
    """Un dossier de cotation : un client, une branche, des compagnies consultées."""
    __tablename__ = "quote_case"
    __table_args__ = (_in("stage", QUOTE_STAGES),)

    id: Mapped[int] = mapped_column(primary_key=True)
    org_id: Mapped[int] = mapped_column(Integer, default=_current_org, server_default="1", index=True)
    ref: Mapped[str] = mapped_column(String(20), index=True)          # COT-2026-0001
    title: Mapped[str] = mapped_column(String(200), default="")
    branch: Mapped[str] = mapped_column(String(40))                   # 1re branche (même libellé que sequence.branch)
    branches: Mapped[list] = mapped_column(JSON, default=list)        # toutes les branches du dossier
    stage: Mapped[str] = mapped_column(String(12), default="new", server_default="new", index=True)
    lost_reason: Mapped[str | None] = mapped_column(String(255))
    company_id: Mapped[int | None] = mapped_column(ForeignKey("company.id", ondelete="SET NULL"), index=True)
    contact_id: Mapped[int | None] = mapped_column(ForeignKey("contact.id", ondelete="SET NULL"), index=True)
    client_name: Mapped[str] = mapped_column(String(255), default="")  # nom affiché (entreprise ou particulier)
    owner_id: Mapped[int | None] = mapped_column(ForeignKey("app_user.id", ondelete="SET NULL"), index=True)
    due_on: Mapped[date | None] = mapped_column(Date, index=True)      # proposition attendue par le client
    current_insurer: Mapped[str | None] = mapped_column(String(120))
    current_premium: Mapped[int | None] = mapped_column(Integer)       # MAD par an
    current_rate: Mapped[str | None] = mapped_column(String(40))       # taux actuel (ex. « 2,5 % »)
    fields: Mapped[dict] = mapped_column(JSON, default=dict)           # fiche de la branche
    notes: Mapped[str] = mapped_column(Text, default="", server_default="")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)
    closed_at: Mapped[datetime | None] = mapped_column(UTCDateTime)


class QuoteInsurer(Base):
    """Une compagnie consultée pour un dossier, et où en est sa réponse."""
    __tablename__ = "quote_insurer"
    __table_args__ = (UniqueConstraint("case_id", "company_id", "branch", name="uq_quote_insurer"),
                      _in("status", QUOTE_INSURER_STATUSES))

    id: Mapped[int] = mapped_column(primary_key=True)
    org_id: Mapped[int] = mapped_column(Integer, default=_current_org, server_default="1", index=True)
    case_id: Mapped[int] = mapped_column(ForeignKey("quote_case.id", ondelete="CASCADE"), index=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("company.id", ondelete="CASCADE"))
    branch: Mapped[str] = mapped_column(String(40))                    # une consultation par branche
    contact_id: Mapped[int | None] = mapped_column(ForeignKey("contact.id", ondelete="SET NULL"))
    recipients: Mapped[list | None] = mapped_column(JSON)              # adresses de la dernière demande (À)
    status: Mapped[str] = mapped_column(String(12), default="to_send", server_default="to_send")
    sent_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    sent_by: Mapped[int | None] = mapped_column(ForeignKey("app_user.id", ondelete="SET NULL"))
    reminders_sent: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    last_message_id: Mapped[str | None] = mapped_column(String(255))  # pour relancer dans le même fil
    # relances automatiques (comme une campagne) : prochaine relance prévue, désactivables
    next_followup_at: Mapped[datetime | None] = mapped_column(UTCDateTime, index=True)
    auto_followups: Mapped[bool] = mapped_column(Boolean, default=True, server_default="1")
    first_subject: Mapped[str | None] = mapped_column(Text)
    replied_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    offer_premium: Mapped[int | None] = mapped_column(Integer)          # MAD par an
    offer_rate: Mapped[str | None] = mapped_column(String(40))          # taux proposé (AT, prévoyance…)
    notes: Mapped[str] = mapped_column(Text, default="", server_default="")
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)


class QuoteEvent(Base):
    """Historique d'un dossier : création, étapes, notes, emails envoyés et reçus, documents."""
    __tablename__ = "quote_event"
    __table_args__ = (_in("kind", QUOTE_EVENT_KINDS),)

    id: Mapped[int] = mapped_column(primary_key=True)
    org_id: Mapped[int] = mapped_column(Integer, default=_current_org, server_default="1", index=True)
    case_id: Mapped[int] = mapped_column(ForeignKey("quote_case.id", ondelete="CASCADE"), index=True)
    insurer_id: Mapped[int | None] = mapped_column(ForeignKey("quote_insurer.id", ondelete="SET NULL"))
    kind: Mapped[str] = mapped_column(String(10))
    text: Mapped[str] = mapped_column(Text, default="")
    data: Mapped[dict | None] = mapped_column(JSON)
    message_id: Mapped[str | None] = mapped_column(String(255), index=True)  # emails : rattachement des réponses
    user_id: Mapped[int | None] = mapped_column(Integer, default=lambda: _current_user())
    ts: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, index=True)


class QuoteFile(Base):
    """Document rangé dans un dossier (pièce du client, offre d'une compagnie…)."""
    __tablename__ = "quote_file"
    __table_args__ = (_in("kind", QUOTE_FILE_KINDS),)

    id: Mapped[int] = mapped_column(primary_key=True)
    org_id: Mapped[int] = mapped_column(Integer, default=_current_org, server_default="1", index=True)
    case_id: Mapped[int] = mapped_column(ForeignKey("quote_case.id", ondelete="CASCADE"), index=True)
    attachment_id: Mapped[int] = mapped_column(ForeignKey("attachment.id", ondelete="CASCADE"))
    insurer_id: Mapped[int | None] = mapped_column(ForeignKey("quote_insurer.id", ondelete="SET NULL"))
    kind: Mapped[str] = mapped_column(String(8), default="client", server_default="client")
    label: Mapped[str] = mapped_column(String(120), default="", server_default="")  # « Liste du parc »…
    user_id: Mapped[int | None] = mapped_column(Integer, default=lambda: _current_user())
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


# ---------------------------------------------------------------------------------------------
# Contrats et échéances. Un contrat = une police chez une compagnie, pour un client et une branche.
# Commun à l'équipe du cabinet (org_id), avec un gestionnaire. Le renouvellement se fait sur la même
# ligne (dates avancées d'un an, période précédente gardée dans `history`) ; un changement de
# compagnie termine le contrat et en crée un nouveau (`previous_id`).

CONTRACT_STATUSES = ("active", "renewing", "ended")


class Contract(Base):
    __tablename__ = "contract"
    __table_args__ = (_in("status", CONTRACT_STATUSES),)

    id: Mapped[int] = mapped_column(primary_key=True)
    org_id: Mapped[int] = mapped_column(Integer, default=_current_org, server_default="1", index=True)
    client_name: Mapped[str] = mapped_column(String(255), default="")
    company_id: Mapped[int | None] = mapped_column(ForeignKey("company.id", ondelete="SET NULL"), index=True)
    contact_id: Mapped[int | None] = mapped_column(ForeignKey("contact.id", ondelete="SET NULL"), index=True)
    insurer_id: Mapped[int | None] = mapped_column(ForeignKey("company.id", ondelete="SET NULL"), index=True)
    insurer_name: Mapped[str] = mapped_column(String(120), default="", server_default="")  # si compagnie hors base
    branch: Mapped[str] = mapped_column(String(40))
    policy_number: Mapped[str] = mapped_column(String(60), default="", server_default="")
    premium: Mapped[int | None] = mapped_column(Integer)                  # prime nette, MAD par an
    rate: Mapped[str | None] = mapped_column(String(40))                  # taux (AT, prévoyance…)
    base_amount: Mapped[int | None] = mapped_column(Integer)              # masse salariale, CA… (voir branche)
    accessories: Mapped[int | None] = mapped_column(Integer)              # accessoires / coût de police
    tax_rate: Mapped[float | None] = mapped_column(Float)                 # taux total des taxes (%) ; vide = à compléter
    parafiscal_rate: Mapped[float | None] = mapped_column(Float)          # (0018, inutilisé : compris dans tax_rate)
    evcat_rate: Mapped[float | None] = mapped_column(Float)               # EVCAT, % de la prime nette
    evcat_cap: Mapped[int | None] = mapped_column(Integer)                # plafond de l'EVCAT (MAD)
    commission_rate: Mapped[float | None] = mapped_column(Float)          # % de la prime nette
    start_date: Mapped[date | None] = mapped_column(Date)                 # effet de la période en cours
    end_date: Mapped[date] = mapped_column(Date, index=True)              # échéance
    notice_days: Mapped[int] = mapped_column(Integer, default=60, server_default="60")  # préavis de résiliation
    tacit: Mapped[bool] = mapped_column(Boolean, default=True, server_default="1")       # tacite reconduction
    status: Mapped[str] = mapped_column(String(10), default="active", server_default="active", index=True)
    end_reason: Mapped[str | None] = mapped_column(String(255))
    owner_id: Mapped[int | None] = mapped_column(ForeignKey("app_user.id", ondelete="SET NULL"), index=True)
    quote_case_id: Mapped[int | None] = mapped_column(ForeignKey("quote_case.id", ondelete="SET NULL"), index=True)
    renewal_case_id: Mapped[int | None] = mapped_column(ForeignKey("quote_case.id", ondelete="SET NULL"), index=True)
    previous_id: Mapped[int | None] = mapped_column(ForeignKey("contract.id", ondelete="SET NULL"))
    notes: Mapped[str] = mapped_column(Text, default="", server_default="")
    history: Mapped[list] = mapped_column(JSON, default=list)             # [{ts, text}] : périodes, changements
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)


# ---------------------------------------------------------------------------------------------
# V3.6 : listes de contacts. Une liste est personnelle (son auteur) et peut être partagée avec
# l'équipe. Remplie à l'import, à la main depuis Contacts, ou depuis une campagne (sans-réponse).

LIST_SOURCES = ("manual", "import", "campaign")


class ContactList(Base):
    __tablename__ = "contact_list"
    __table_args__ = (_in("source", LIST_SOURCES),)

    id: Mapped[int] = mapped_column(primary_key=True)
    org_id: Mapped[int] = mapped_column(Integer, default=_current_org, server_default="1", index=True)
    name: Mapped[str] = mapped_column(String(120))
    owner_id: Mapped[int | None] = mapped_column(ForeignKey("app_user.id", ondelete="SET NULL"), index=True)
    shared: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    source: Mapped[str] = mapped_column(String(10), default="manual", server_default="manual")
    lot_number: Mapped[int | None] = mapped_column(Integer)  # V3.7 : lot créé par un import ou une recherche
    # V3.8 : liste confiée à un collègue (il en devient le propriétaire ; celui qui confie la voit toujours)
    assigned_by: Mapped[int | None] = mapped_column(ForeignKey("app_user.id", ondelete="SET NULL"))
    assigned_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    assign_note: Mapped[str | None] = mapped_column(String(2000))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)


class ContactListMember(Base):
    __tablename__ = "contact_list_member"
    __table_args__ = (UniqueConstraint("list_id", "contact_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    list_id: Mapped[int] = mapped_column(ForeignKey("contact_list.id", ondelete="CASCADE"), index=True)
    contact_id: Mapped[int] = mapped_column(ForeignKey("contact.id", ondelete="CASCADE"), index=True)
    added_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


# ---------------------------------------------------------------------------------------------
# V3.7 : recherches de prospects via looot (administrateur). L'état (page suivante, file de
# profils à traiter) est gardé ici : une recherche reprend où elle en était après un redémarrage.

PROSPECT_SEARCH_STATUSES = ("preview", "running", "done", "stopped", "failed")


class ProspectSearch(Base):
    __tablename__ = "prospect_search"
    __table_args__ = (_in("status", PROSPECT_SEARCH_STATUSES),)

    id: Mapped[int] = mapped_column(primary_key=True)
    org_id: Mapped[int] = mapped_column(Integer, default=_current_org, server_default="1", index=True)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("app_user.id", ondelete="SET NULL"))
    criteria: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(10), default="preview", server_default="preview", index=True)
    wanted: Mapped[int] = mapped_column(Integer, default=50)
    total_found: Mapped[int | None] = mapped_column(Integer)
    checked: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    emails_found: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    imported: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    skipped_existing: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    skipped_no_email: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    skipped_excluded: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    failures: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    cost_usd: Mapped[float] = mapped_column(default=0.0, server_default="0")
    list_id: Mapped[int | None] = mapped_column(ForeignKey("contact_list.id", ondelete="SET NULL"))
    state: Mapped[dict] = mapped_column(JSON, default=dict)
    error: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)


class AddressBook(Base):
    """V3.7 : carnet d'adresses appris (adresses écrites et expéditeurs reçus), propre à chaque employé,
    pour proposer la fin de l'adresse pendant la saisie (« yassine » → yassine.laoud@…)."""
    __tablename__ = "address_book"
    __table_args__ = (UniqueConstraint("user_id", "email", name="uq_address_book"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("app_user.id", ondelete="CASCADE"), index=True)
    email: Mapped[str] = mapped_column(String(254))  # en minuscules
    name: Mapped[str | None] = mapped_column(String(200))
    uses: Mapped[int] = mapped_column(Integer, default=0, server_default="0")  # emails que vous lui avez écrits
    last_used: Mapped[datetime | None] = mapped_column(UTCDateTime)
    last_seen: Mapped[datetime | None] = mapped_column(UTCDateTime)          # dernier email reçu de lui


class MailDraft(Base):
    """V3.9.2 : brouillon d'un email écrit dans l'appli (Nouveau message, Répondre, Transférer),
    enregistré tout seul pendant la frappe et propre à chaque employé. Supprimé à l'envoi."""
    __tablename__ = "mail_draft"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("app_user.id", ondelete="CASCADE"), index=True)
    to_addr: Mapped[str] = mapped_column(Text, default="")
    subject: Mapped[str] = mapped_column(String(500), default="")
    body: Mapped[str] = mapped_column(Text, default="")
    data: Mapped[dict] = mapped_column(JSON, default=dict)  # Cc, Cci, réponse à, citation, pièces jointes…
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)

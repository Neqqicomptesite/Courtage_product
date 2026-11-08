"""Cotalis, phase 1 : dossiers de cotation.

Un dossier = un client, une branche, une fiche de renseignements propre à la branche, des
documents, et les compagnies consultées. Pour chaque compagnie, l'email de demande est préparé
à partir du modèle de la branche (Séquences → Souscription, étape 1) : les champs entre crochets
([Activité], [Effectif]…) sont remplis avec la fiche du dossier. L'employé relit, puis l'email
part depuis SA boîte (même chemin que les emails écrits à la main : mode test, copie dans
« Envoyés », liste d'exclusion). Les relances reprennent les étapes 2 et 3 du modèle, dans le
même fil.

Une relance est proposée dans l'Agenda N jours ouvrés après l'envoi (réglage du cabinet
« quote_followup_days », 4 par défaut). Quand la compagnie répond dans le fil, la réponse est
rattachée au dossier par la synchronisation de la boîte et le rappel est clos.

Les dossiers sont communs à l'équipe du cabinet (filtre org_id dans app/scope.py).
"""
from __future__ import annotations

import json
import re
from datetime import date, datetime
from email import message_from_bytes, policy
from functools import lru_cache

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import render, settings_store
from app.current import user_id
from app.models import (
    Attachment, Company, Contact, QuoteCase, QuoteEvent, QuoteFile, QuoteInsurer, Reminder, Sequence, Step,
    StepVariant, QUOTE_STAGES,
)
from app.paths import PROJECT_DIR
from app.timeutil import to_local, utcnow

CLIENT_PLACEHOLDER = "Nom du client"
OPEN_STAGES = ("new", "info", "consulting", "offers", "proposed")
STAGE_LABELS = {"new": "Nouveau", "info": "Infos client à réunir", "consulting": "Consultation des compagnies",
                "offers": "Offres reçues", "proposed": "Proposition envoyée", "won": "Gagné", "lost": "Perdu"}
INSURER_LABELS = {"to_send": "À envoyer", "sent": "Envoyé", "reminded": "Relancé", "replied": "A répondu",
                  "offer": "Offre reçue", "declined": "Refus"}


class QuoteError(ValueError):
    def __init__(self, errors: dict[str, str] | str):
        if isinstance(errors, str):
            errors = {"_": errors}
        super().__init__(" ".join(errors.values()))
        self.errors = errors


# --------------------------------------------------------------------------- branches

@lru_cache(maxsize=1)
def _branches_file() -> dict:
    return json.loads((PROJECT_DIR / "app" / "starter" / "branches.json").read_text(encoding="utf-8"))


def branches() -> list[dict]:
    return _branches_file()["branches"]


def branch_def(name: str) -> dict:
    """Fiche de la branche ; une branche inconnue (ajoutée par le cabinet) n'a pas de champs."""
    for b in branches():
        if b["name"] == name:
            return b
    return {"name": name, "fields": [], "docs": []}


def _fmt_number(value) -> str:
    try:
        n = float(str(value).replace(" ", "").replace(" ", "").replace(",", "."))
    except ValueError:
        return str(value)
    if n.is_integer():
        return f"{int(n):,}".replace(",", " ")
    return f"{n:,.2f}".replace(",", " ").replace(".", ",")


def format_value(field: dict, value) -> str:
    if value is None or str(value).strip() == "":
        return ""
    t = field.get("type", "text")
    if t == "number":
        return _fmt_number(value)
    if t == "date":
        try:
            return date.fromisoformat(str(value)).strftime("%d/%m/%Y")
        except ValueError:
            return str(value)
    return str(value).strip()


def clean_fields(branch: str, values: dict | None) -> dict:
    """Ne garde que les champs de la branche, en texte, sans espaces en trop."""
    keys = {f["key"]: f for f in branch_def(branch)["fields"]}
    out = {}
    for k, v in (values or {}).items():
        if k in keys and v is not None and str(v).strip() != "":
            out[k] = str(v).strip()[:2000]
    return out


def missing_fields(case: QuoteCase) -> list[str]:
    vals = case.fields or {}
    return [f["label"] for f in branch_def(case.branch)["fields"] if not str(vals.get(f["key"], "")).strip()]


def fill(text: str, case: QuoteCase) -> str:
    """Remplace les [champs] du modèle par les valeurs du dossier ; les autres restent à compléter."""
    values = {CLIENT_PLACEHOLDER: case.client_name}
    for f in branch_def(case.branch)["fields"]:
        v = format_value(f, (case.fields or {}).get(f["key"]))
        if v and f.get("placeholder"):
            values[f["placeholder"]] = v

    def rep(m: re.Match) -> str:
        return values.get(m.group(1).strip()) or m.group(0)
    return render.PLACEHOLDER_RE.sub(rep, text or "")


# --------------------------------------------------------------------------- dossiers

def next_ref(s: Session, now: datetime | None = None) -> str:
    year = to_local(now or utcnow()).year
    prefix = f"COT-{year}-"
    last = s.scalar(select(func.max(QuoteCase.ref)).where(QuoteCase.ref.like(prefix + "%")))
    n = int(last.rsplit("-", 1)[1]) + 1 if last else 1
    return f"{prefix}{n:04d}"


def event(s: Session, case: QuoteCase, kind: str, text: str, insurer: QuoteInsurer | None = None,
          data: dict | None = None, message_id: str | None = None) -> QuoteEvent:
    ev = QuoteEvent(case_id=case.id, insurer_id=insurer.id if insurer else None, kind=kind, text=text,
                    data=data, message_id=message_id)
    s.add(ev)
    return ev


def _parse_date(value) -> date | None:
    if value in (None, ""):
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        raise QuoteError({"due_on": "Date invalide."}) from None


def _parse_amount(value, key: str) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(round(float(str(value).replace(" ", "").replace(" ", "").replace(",", "."))))
    except ValueError:
        raise QuoteError({key: "Montant invalide (chiffres uniquement)."}) from None


def create(s: Session, data: dict) -> QuoteCase:
    branch = str(data.get("branch") or "").strip()
    errors = {}
    if not branch:
        errors["branch"] = "Choisissez la branche."
    company = s.get(Company, int(data["company_id"])) if data.get("company_id") else None
    contact = s.get(Contact, int(data["contact_id"])) if data.get("contact_id") else None
    if contact and not company and contact.company_id:
        company = s.get(Company, contact.company_id)
    client = str(data.get("client_name") or "").strip() or (company.name if company else "") or (
        " ".join(x for x in [contact.first_name, contact.last_name] if x) if contact else "")
    if not client:
        errors["client_name"] = "Indiquez le client (entreprise ou contact)."
    if errors:
        raise QuoteError(errors)
    case = QuoteCase(ref=next_ref(s), branch=branch[:40], client_name=client[:255],
                     title=str(data.get("title") or "").strip()[:200] or f"{branch} – {client}"[:200],
                     company_id=company.id if company else None, contact_id=contact.id if contact else None,
                     owner_id=int(data["owner_id"]) if data.get("owner_id") else user_id(),
                     due_on=_parse_date(data.get("due_on")), current_insurer=(data.get("current_insurer") or None),
                     current_premium=_parse_amount(data.get("current_premium"), "current_premium"),
                     fields=clean_fields(branch, data.get("fields")), notes=str(data.get("notes") or ""))
    case.stage = "info" if missing_fields(case) else "new"
    s.add(case)
    s.flush()
    event(s, case, "created", f"Dossier créé ({branch})")
    return case


EDITABLE = ("title", "branch", "client_name", "company_id", "contact_id", "owner_id", "due_on",
            "current_insurer", "current_premium", "notes", "lost_reason")


def update(s: Session, case: QuoteCase, data: dict) -> QuoteCase:
    changed = []
    for k in EDITABLE:
        if k not in data:
            continue
        v = data[k]
        if k == "due_on":
            v = _parse_date(v)
        elif k == "current_premium":
            v = _parse_amount(v, k)
        elif k in ("company_id", "contact_id", "owner_id"):
            v = int(v) if v not in (None, "") else None
        elif isinstance(v, str):
            v = v.strip() or (None if k in ("current_insurer", "lost_reason") else "")
        if k == "branch" and not v:
            raise QuoteError({"branch": "Choisissez la branche."})
        if k == "client_name" and not v:
            raise QuoteError({"client_name": "Indiquez le client."})
        if getattr(case, k) != v:
            setattr(case, k, v)
            changed.append(k)
    if "fields" in data:
        new = {**(case.fields or {}), **clean_fields(case.branch, data["fields"])}
        for key, val in (data["fields"] or {}).items():  # champ vidé
            if val in (None, "") and key in new:
                new.pop(key)
        if new != (case.fields or {}):
            case.fields = new
            event(s, case, "fields", "Fiche de renseignements mise à jour")
    if "branch" in changed:
        case.fields = clean_fields(case.branch, case.fields)
    if "stage" in data and data["stage"] != case.stage:
        set_stage(s, case, str(data["stage"]), data.get("lost_reason"))
    if changed and changed != ["notes"]:
        event(s, case, "edit", "Dossier modifié : " + ", ".join(_FIELD_LABELS.get(k, k) for k in changed))
    return case


_FIELD_LABELS = {"title": "intitulé", "branch": "branche", "client_name": "client", "company_id": "entreprise",
                 "contact_id": "interlocuteur", "owner_id": "responsable", "due_on": "date attendue",
                 "current_insurer": "assureur actuel", "current_premium": "prime actuelle", "lost_reason": "motif"}


def set_stage(s: Session, case: QuoteCase, stage: str, lost_reason: str | None = None) -> None:
    if stage not in QUOTE_STAGES:
        raise QuoteError({"stage": "Étape inconnue."})
    if stage == "lost" and not (lost_reason or case.lost_reason or "").strip():
        raise QuoteError({"lost_reason": "Indiquez le motif de la perte."})
    before = case.stage
    case.stage = stage
    if stage == "lost":
        case.lost_reason = (lost_reason or case.lost_reason or "").strip()[:255]
    case.closed_at = utcnow() if stage in ("won", "lost") else None
    if stage in ("won", "lost"):
        _close_reminders(s, case)
    event(s, case, "stage", f"{STAGE_LABELS[before]} → {STAGE_LABELS[stage]}"
          + (f" ({case.lost_reason})" if stage == "lost" else ""), data={"from": before, "to": stage})


def _advance(s: Session, case: QuoteCase, stage: str) -> None:
    """Avance automatique (jamais de retour en arrière, jamais après « Proposition envoyée »)."""
    order = list(QUOTE_STAGES)
    if case.stage in OPEN_STAGES[:4] and order.index(stage) > order.index(case.stage):
        set_stage(s, case, stage)


# --------------------------------------------------------------------------- compagnies

def default_contact(s: Session, company_id: int) -> Contact | None:
    """L'interlocuteur à qui écrire chez une compagnie : service souscription d'abord."""
    people = list(s.scalars(select(Contact).where(Contact.company_id == company_id,
                                                  Contact.global_status != "do_not_contact")
                            .order_by(Contact.id)))
    for dept in ("souscription", "production", None):
        for c in people:
            if dept is None or c.department == dept:
                return c
    return None


def add_insurers(s: Session, case: QuoteCase, company_ids: list[int]) -> list[QuoteInsurer]:
    have = {qi.company_id for qi in s.scalars(select(QuoteInsurer).where(QuoteInsurer.case_id == case.id))}
    added = []
    for cid in dict.fromkeys(int(x) for x in company_ids):
        comp = s.get(Company, cid)
        if comp is None or cid in have:
            continue
        c = default_contact(s, cid)
        qi = QuoteInsurer(case_id=case.id, company_id=cid, contact_id=c.id if c else None)
        s.add(qi)
        s.flush()
        event(s, case, "insurer", f"{comp.name} ajoutée aux compagnies à consulter", qi)
        added.append(qi)
    return added


def template_steps(s: Session, branch: str) -> list[tuple[str, str, bool]]:
    """Étapes (objet, corps, même fil) du modèle de cotation de la branche, ou une version simple."""
    seqs = list(s.scalars(select(Sequence).where(Sequence.category == "souscription", Sequence.branch == branch)
                          .order_by(Sequence.owner_id.is_not(None), Sequence.id)))
    if seqs:
        steps = list(s.scalars(select(Step).where(Step.sequence_id == seqs[0].id).order_by(Step.position)))
        out = []
        for st in steps:
            v = s.scalars(select(StepVariant).where(StepVariant.step_id == st.id).order_by(StepVariant.label)).first()
            out.append((v.subject_template if v else "", st.body_template, st.same_thread))
        if out:
            return out
    return [(f"Demande de cotation {branch} – [{CLIENT_PLACEHOLDER}]",
             'Bonjour {{ prenom | "Madame, Monsieur" }},\n\nNous vous sollicitons pour une cotation '
             f"{branch.lower()} au profit de notre client [{CLIENT_PLACEHOLDER}].\n\n"
             "Merci de nous adresser votre meilleure proposition (garanties, franchises, prime).\n\nBien cordialement,",
             False),
            ("", 'Bonjour {{ prenom | "Madame, Monsieur" }},\n\nJe me permets de revenir vers vous concernant la '
                 "demande de cotation ci-dessous. Pourriez-vous m'indiquer quand nous pourrons recevoir votre "
                 "proposition ?\n\nBien cordialement,", True)]


def _render_vars(text: str, contact: Contact | None) -> str:
    ctx = render.RenderContext(contact=contact or Contact(email=""), signature="", target_blocks={}, sector_blocks={})
    return render.render(text, ctx).text


def draft(s: Session, case: QuoteCase, qi: QuoteInsurer) -> dict:
    """Email prêt à relire : demande (première fois) ou relance (ensuite, dans le même fil)."""
    steps = template_steps(s, case.branch)
    contact = s.get(Contact, qi.contact_id) if qi.contact_id else None
    followup = qi.status != "to_send" and bool(qi.last_message_id)
    if followup:
        idx = min(1 + qi.reminders_sent, len(steps) - 1) if len(steps) > 1 else 0
        subj_t, body_t, _same = steps[idx]
        subject = qi.first_subject or fill(_render_vars(steps[0][0], contact), case)
        subject = subject if subject.lower().startswith("re:") else f"Re: {subject}"
    else:
        subj_t, body_t, _same = steps[0]
        subject = fill(_render_vars(subj_t, contact), case)
    body = fill(_render_vars(body_t, contact), case)
    files = list(s.execute(select(QuoteFile, Attachment).join(Attachment, Attachment.id == QuoteFile.attachment_id)
                           .where(QuoteFile.case_id == case.id, QuoteFile.kind == "client")))
    return {"to": contact.email if contact else "", "subject": subject, "body": body, "followup": followup,
            "in_reply_to": qi.last_message_id if followup else None,
            "references": [qi.last_message_id] if followup and qi.last_message_id else [],
            "missing": render.placeholders(subject + "\n" + body),
            "attachments": [] if followup else [{"id": a.id, "name": a.filename, "size": a.size, "label": f.label}
                                                for f, a in files]}


def send(s: Session, case: QuoteCase, qi: QuoteInsurer, body: dict, smtp_factory=None, imap_factory=None) -> QuoteInsurer:
    from app import manual_mail
    d = manual_mail.draft_from(body)
    left = render.placeholders(d.subject + "\n" + d.body)
    if left:
        raise QuoteError({"body": "Champs encore à compléter : " + ", ".join(f"[{p}]" for p in left)})
    followup = qi.status != "to_send" and bool(qi.last_message_id)
    if followup:
        d.in_reply_to = qi.last_message_id
        d.references = [qi.last_message_id]
    out = manual_mail.send(s, d, smtp_factory=smtp_factory, imap_factory=imap_factory)  # commit inclus
    comp = s.get(Company, qi.company_id)
    now = utcnow()
    if followup:
        qi.reminders_sent += 1
        qi.status = "reminded" if qi.status in ("sent", "reminded") else qi.status
    else:
        qi.status, qi.sent_at, qi.first_subject = "sent", now, d.subject
    qi.sent_by = user_id()
    qi.last_message_id = out.message_id
    if contact := s.scalars(select(Contact).where(Contact.email == d.to[0])).first():
        qi.contact_id = contact.id
    event(s, case, "email_out", f"{'Relance' if followup else 'Demande de cotation'} envoyée à {comp.name if comp else ''}"
          f" ({', '.join(d.to)})" + (" – mode test" if out.test_mode else ""), qi,
          data={"subject": d.subject, "body": d.body[:4000], "to": d.to, "attachments": out.attachments or [],
                "test_mode": out.test_mode}, message_id=out.message_id)
    _close_reminders(s, case, qi.company_id)
    _schedule_followup(s, case, qi, comp)
    _advance(s, case, "consulting")
    s.commit()
    return qi


def _schedule_followup(s: Session, case: QuoteCase, qi: QuoteInsurer, comp: Company | None) -> Reminder:
    from app.scheduling import SendWindow
    days = int(settings_store.get(s, "quote_followup_days") or 4)
    due = SendWindow.from_settings(s).add_days(to_local(utcnow()).date(), days, True)
    r = Reminder(kind="quote", title=f"Relancer {comp.name if comp else 'la compagnie'} · {case.client_name} ({case.ref})"[:255],
                 notes=f"Dossier {case.ref} – {case.branch}. Sans réponse : relance proposée depuis le dossier.",
                 due_on=due, company_id=qi.company_id, user_id=user_id(), quote_case_id=case.id)
    s.add(r)
    return r


def _close_reminders(s: Session, case: QuoteCase, company_id: int | None = None) -> int:
    """Clôt les rappels ouverts du dossier (de toute l'équipe : le dossier est commun)."""
    q = select(Reminder).where(Reminder.quote_case_id == case.id, Reminder.done_at.is_(None))
    if company_id is not None:
        q = q.where(Reminder.company_id == company_id)
    n = 0
    for r in s.scalars(q.execution_options(oddo_all=True)):  # rappels de tous les employés : dossier commun
        r.done_at = utcnow()
        n += 1
    return n


def set_insurer(s: Session, case: QuoteCase, qi: QuoteInsurer, data: dict) -> QuoteInsurer:
    comp = s.get(Company, qi.company_id)
    if "contact_id" in data:
        cid = int(data["contact_id"]) if data["contact_id"] else None
        if cid is not None:
            c = s.get(Contact, cid)
            if c is None:
                raise QuoteError({"contact_id": "Interlocuteur introuvable."})
        qi.contact_id = cid
    if "offer_premium" in data:
        qi.offer_premium = _parse_amount(data["offer_premium"], "offer_premium")
    if "notes" in data:
        qi.notes = str(data["notes"] or "")
    if "status" in data and data["status"] != qi.status:
        st = str(data["status"])
        if st not in INSURER_LABELS:
            raise QuoteError({"status": "Statut inconnu."})
        qi.status = st
        if st in ("replied", "offer", "declined"):
            qi.replied_at = qi.replied_at or utcnow()
            _close_reminders(s, case, qi.company_id)
        event(s, case, "insurer", f"{comp.name if comp else 'Compagnie'} : {INSURER_LABELS[st]}"
              + (f" – {_fmt_number(qi.offer_premium)} MAD" if st == "offer" and qi.offer_premium else ""), qi)
        if st == "offer":
            _advance(s, case, "offers")
    return qi


def remove_insurer(s: Session, case: QuoteCase, qi: QuoteInsurer) -> None:
    if qi.status != "to_send":
        raise QuoteError("Cette compagnie a déjà été consultée : marquez plutôt « Refus » ou laissez-la dans le dossier.")
    comp = s.get(Company, qi.company_id)
    event(s, case, "insurer", f"{comp.name if comp else 'Compagnie'} retirée du dossier")
    s.delete(qi)


# --------------------------------------------------------------------------- documents

def add_file(s: Session, case: QuoteCase, attachment_id: int, kind: str = "client", label: str = "",
             insurer_id: int | None = None) -> QuoteFile:
    att = s.get(Attachment, attachment_id)
    if att is None:
        raise QuoteError({"file": "Fichier introuvable."})
    if kind not in ("client", "offer", "other"):
        kind = "other"
    qi = s.get(QuoteInsurer, insurer_id) if insurer_id else None
    if qi is not None and qi.case_id != case.id:
        qi = None
    f = QuoteFile(case_id=case.id, attachment_id=att.id, kind=kind, label=str(label or "")[:120],
                  insurer_id=qi.id if qi else None)
    s.add(f)
    s.flush()
    comp = s.get(Company, qi.company_id) if qi else None
    event(s, case, "file", f"Document ajouté : {att.filename}" + (f" (offre {comp.name})" if comp and kind == "offer" else ""),
          qi, data={"file_id": f.id, "name": att.filename})
    if kind == "offer" and qi is not None and qi.status not in ("offer",):
        set_insurer(s, case, qi, {"status": "offer"})
    return f


# --------------------------------------------------------------------------- réponses reçues

def on_inbound(s: Session, mailbox_id: int, a, raw: bytes, folder: str | None, uid: int | None) -> bool:
    """Appelé par la synchronisation de la boîte : une réponse dans le fil d'une demande de
    cotation est rattachée au dossier. Renvoie True si l'email a été pris en charge."""
    ids = [i for i in (a.referenced_ids or []) if i]
    if not ids:
        return False
    sent = s.scalars(select(QuoteEvent).where(QuoteEvent.kind == "email_out", QuoteEvent.message_id.in_(ids))
                     .order_by(QuoteEvent.id.desc())).first()
    if sent is None or sent.insurer_id is None:
        return False
    if a.message_id and s.scalar(select(func.count(QuoteEvent.id)).where(
            QuoteEvent.kind == "email_in", QuoteEvent.message_id == a.message_id)):
        return True  # déjà rattachée
    case = s.get(QuoteCase, sent.case_id)
    qi = s.get(QuoteInsurer, sent.insurer_id)
    if case is None or qi is None:
        return False
    names = []  # pièces jointes : nom + position dans l'email (pour « Ajouter au dossier »)
    try:
        from app.mailbox_browser import _leaves, _part_name
        msg = message_from_bytes(raw, policy=policy.default)
        names = [{"name": _part_name(p, i), "index": i} for i, p in enumerate(_leaves(msg))
                 if p.get_filename() or p.get_content_disposition() == "attachment"][:20]
    except Exception:  # noqa: BLE001 – une pièce jointe illisible n'empêche pas le rattachement
        pass
    comp = s.get(Company, qi.company_id)
    auto = a.kind == "auto_reply"
    event(s, case, "email_in", f"{'Réponse automatique' if auto else 'Réponse'} de {comp.name if comp else a.sender}"
          f" ({a.sender})", qi, message_id=a.message_id,
          data={"subject": a.subject[:500], "body": (a.text or "")[:6000], "from": a.sender,
                "received_at": a.received_at.isoformat() if a.received_at else None, "folder": folder, "uid": uid,
                "mailbox_id": mailbox_id, "attachments": names, "auto_reply": auto})
    if not auto and qi.status in ("sent", "reminded"):
        qi.status, qi.replied_at = "replied", utcnow()
        _close_reminders(s, case, qi.company_id)
    return True


# --------------------------------------------------------------------------- JSON

def _user_names(s: Session) -> dict[int, str]:
    from app.models import AppUser
    return {u.id: (u.full_name or u.email) for u in s.scalars(select(AppUser))}


def summary_json(case: QuoteCase, insurers: list[QuoteInsurer], users: dict[int, str]) -> dict:
    today = to_local(utcnow()).date()
    counts = {k: 0 for k in INSURER_LABELS}
    for qi in insurers:
        counts[qi.status] += 1
    return {"id": case.id, "ref": case.ref, "title": case.title, "branch": case.branch, "stage": case.stage,
            "client_name": case.client_name, "company_id": case.company_id, "contact_id": case.contact_id,
            "owner_id": case.owner_id, "owner_name": users.get(case.owner_id) if case.owner_id else None,
            "due_on": case.due_on.isoformat() if case.due_on else None,
            "late": bool(case.due_on and case.due_on < today and case.stage in OPEN_STAGES),
            "missing": len(missing_fields(case)), "insurers": len(insurers), "insurer_counts": counts,
            "best_offer": min((qi.offer_premium for qi in insurers if qi.status == "offer" and qi.offer_premium), default=None),
            "current_premium": case.current_premium, "lost_reason": case.lost_reason,
            "created_at": case.created_at.isoformat(), "updated_at": case.updated_at.isoformat()}


def list_json(s: Session) -> list[dict]:
    cases = list(s.scalars(select(QuoteCase).order_by(QuoteCase.updated_at.desc())))
    ins: dict[int, list[QuoteInsurer]] = {}
    if cases:
        for qi in s.scalars(select(QuoteInsurer).where(QuoteInsurer.case_id.in_([c.id for c in cases]))):
            ins.setdefault(qi.case_id, []).append(qi)
    users = _user_names(s)
    return [summary_json(c, ins.get(c.id, []), users) for c in cases]


def detail_json(s: Session, case: QuoteCase) -> dict:
    from app.attachments_service import as_json as att_json
    users = _user_names(s)
    insurers = list(s.scalars(select(QuoteInsurer).where(QuoteInsurer.case_id == case.id).order_by(QuoteInsurer.id)))
    comps = {c.id: c for c in s.scalars(select(Company).where(Company.id.in_(
        [qi.company_id for qi in insurers] + ([case.company_id] if case.company_id else []))))}
    cids = [qi.contact_id for qi in insurers if qi.contact_id] + ([case.contact_id] if case.contact_id else [])
    contacts = {c.id: c for c in s.scalars(select(Contact).where(Contact.id.in_(cids)))} if cids else {}
    files = list(s.execute(select(QuoteFile, Attachment).join(Attachment, Attachment.id == QuoteFile.attachment_id)
                           .where(QuoteFile.case_id == case.id).order_by(QuoteFile.id)))
    events = list(s.scalars(select(QuoteEvent).where(QuoteEvent.case_id == case.id).order_by(QuoteEvent.ts.desc(), QuoteEvent.id.desc())))

    def person(c: Contact | None) -> dict | None:
        if c is None:
            return None
        return {"id": c.id, "email": c.email, "name": " ".join(x for x in [c.first_name, c.last_name] if x) or c.email,
                "department": c.department}

    from app.mailbox_service import get_primary
    mb = get_primary(s)
    my_box = mb.id if mb else None
    bdef = branch_def(case.branch)
    return {**summary_json(case, insurers, users),
            "fields": case.fields or {}, "notes": case.notes, "current_insurer": case.current_insurer,
            "closed_at": case.closed_at.isoformat() if case.closed_at else None,
            "branch_def": bdef, "missing_labels": missing_fields(case),
            "company": {"id": comps[case.company_id].id, "name": comps[case.company_id].name} if case.company_id in comps else None,
            "contact": person(contacts.get(case.contact_id)) if case.contact_id else None,
            "insurer_list": [{
                "id": qi.id, "company_id": qi.company_id, "company": comps[qi.company_id].name if qi.company_id in comps else "?",
                "logo": (f"/api/companies/{qi.company_id}/logo?v={comps[qi.company_id].logo}"
                         if qi.company_id in comps and comps[qi.company_id].logo else None),
                "contact": person(contacts.get(qi.contact_id)) if qi.contact_id else None,
                "status": qi.status, "sent_at": qi.sent_at.isoformat() if qi.sent_at else None,
                "replied_at": qi.replied_at.isoformat() if qi.replied_at else None,
                "reminders_sent": qi.reminders_sent, "offer_premium": qi.offer_premium, "notes": qi.notes,
                "sent_by_name": users.get(qi.sent_by) if qi.sent_by else None,
            } for qi in insurers],
            "files": [{**att_json(a), "file_id": f.id, "kind": f.kind, "label": f.label, "insurer_id": f.insurer_id,
                       "created_at": f.created_at.isoformat()} for f, a in files],
            "events": [{"id": e.id, "kind": e.kind, "text": e.text, "data": e.data, "insurer_id": e.insurer_id,
                        "user_name": users.get(e.user_id) if e.user_id else None, "ts": e.ts.isoformat(),
                        "mine": bool(e.data and my_box is not None and e.data.get("mailbox_id") == my_box)}
                       for e in events[:200]]}


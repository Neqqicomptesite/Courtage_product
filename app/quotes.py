"""Dossiers de cotation.

Un dossier = un client, une ou plusieurs branches (AT + prévoyance + flotte…), une fiche de
renseignements (les champs communs, comme l'activité ou l'effectif, ne se saisissent qu'une
fois), des documents, des rappels, et les compagnies consultées : une ligne par compagnie ET
par branche (souvent, ce ne sont pas les mêmes souscripteurs selon la branche).

L'email de demande est préparé à partir du modèle de la branche (Séquences → Souscription,
étape 1) : les champs entre crochets ([Activité], [Effectif]…) sont remplis avec la fiche. Pour
une compagnie consultée sur plusieurs branches, on choisit : un email commun (les branches à la
suite) ou un email par branche, chacun à ses destinataires (plusieurs personnes possibles dans
le même email). L'employé relit, puis l'email part depuis SA boîte (même chemin que les emails
écrits à la main : mode test, copie dans « Envoyés », liste d'exclusion). « Envoyer à toutes les
compagnies » prépare et envoie d'un coup, un email commun par compagnie.

Les relances reprennent les étapes 2 et 3 du modèle, dans le même fil. Une relance est proposée
dans l'Agenda N jours ouvrés après chaque envoi (réglage du cabinet « quote_followup_days »,
4 par défaut). Quand la compagnie répond dans le fil, la réponse est rattachée au dossier par la
synchronisation de la boîte et le rappel est clos.

Les dossiers sont communs à l'équipe du cabinet (filtre org_id dans app/scope.py).
"""
from __future__ import annotations

import json
import re
from datetime import date, datetime, time
from email import message_from_bytes, policy
from functools import lru_cache

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import render, settings_store
from app.current import user_id
from app.models import (
    Attachment, Company, Contact, QuoteCase, QuoteEvent, QuoteFile, QuoteInsurer, Reminder, Sequence, Step,
    StepVariant, QUOTE_FILE_KINDS, QUOTE_STAGES, REMINDER_KINDS,
)
from app.paths import PROJECT_DIR
from app.timeutil import to_local, utcnow

CLIENT_PLACEHOLDER = "Nom du client"
OPEN_STAGES = ("new", "info", "consulting", "partial", "offers", "proposed")
AUTO_STAGES = ("new", "info", "consulting", "partial")  # étapes que l'appli peut faire avancer seule
STAGE_LABELS = {"new": "Nouveau", "info": "Infos client à réunir", "consulting": "Consultation des compagnies",
                "partial": "Offres partielles", "offers": "Toutes les offres reçues", "proposed": "Proposition envoyée",
                "won": "Gagné", "lost": "Perdu"}
INSURER_LABELS = {"to_send": "À envoyer", "sent": "Envoyé", "reminded": "Relancé", "replied": "A répondu",
                  "offer": "Offre reçue", "renegotiate": "À renégocier", "declined": "Refus"}
OFFER_STATUSES = ("offer", "renegotiate")
ANSWERED = ("offer", "renegotiate", "declined")


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


def branches_of(case: QuoteCase) -> list[str]:
    return list(case.branches or []) or [case.branch]


def field_defs(names: list[str]) -> list[dict]:
    """Champs de toutes les branches du dossier, chaque clé une seule fois (activité, effectif… communs)."""
    out: dict[str, dict] = {}
    for b in names:
        for f in branch_def(b)["fields"]:
            if f["key"] in out:
                out[f["key"]]["branches"].append(b)
            else:
                out[f["key"]] = {**f, "branches": [b]}
    return list(out.values())


def _fmt_number(value) -> str:
    try:
        n = float(str(value).replace(" ", "").replace(" ", "").replace("\xa0", "").replace(",", "."))
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


def clean_fields(names: list[str], values: dict | None) -> dict:
    """Ne garde que les champs des branches du dossier, en texte, sans espaces en trop."""
    keys = {f["key"] for f in field_defs(names)}
    return {k: str(v).strip()[:2000] for k, v in (values or {}).items()
            if k in keys and v is not None and str(v).strip() != ""}


def missing_fields(case: QuoteCase) -> list[str]:
    vals = case.fields or {}
    return [f["label"] for f in field_defs(branches_of(case))
            if not f.get("optional") and not str(vals.get(f["key"], "")).strip()]


def fill(text: str, case: QuoteCase, branch: str) -> str:
    """Remplace les [champs] du modèle par les valeurs du dossier. Champ facultatif vide : sa ligne
    est retirée. Les autres champs vides restent entre crochets (à compléter avant l'envoi)."""
    values = {CLIENT_PLACEHOLDER: case.client_name}
    drop = set()
    for f in branch_def(branch)["fields"]:
        if not f.get("placeholder"):
            continue
        v = format_value(f, (case.fields or {}).get(f["key"]))
        if v:
            values[f["placeholder"]] = v
        elif f.get("optional"):
            drop.add(f["placeholder"])
    lines = [ln for ln in (text or "").split("\n")
             if not any(f"[{p}]" in ln for p in drop)]

    def rep(m: re.Match) -> str:
        return values.get(m.group(1).strip()) or m.group(0)
    return render.PLACEHOLDER_RE.sub(rep, "\n".join(lines))


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


def _parse_date(value, key: str = "due_on") -> date | None:
    if value in (None, ""):
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        raise QuoteError({key: "Date invalide."}) from None


def _parse_amount(value, key: str) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(round(float(str(value).replace(" ", "").replace(" ", "").replace("\xa0", "").replace(",", "."))))
    except ValueError:
        raise QuoteError({key: "Montant invalide (chiffres uniquement)."}) from None


def _branch_list(value) -> list[str]:
    items = value if isinstance(value, list) else [value] if value else []
    return list(dict.fromkeys(str(b).strip()[:40] for b in items if str(b or "").strip()))


def create(s: Session, data: dict) -> QuoteCase:
    names = _branch_list(data.get("branches")) or _branch_list(data.get("branch"))
    errors = {}
    if not names:
        errors["branch"] = "Choisissez au moins une branche."
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
    case = QuoteCase(ref=next_ref(s), branch=names[0], branches=names, client_name=client[:255],
                     title=str(data.get("title") or "").strip()[:200] or f"{' + '.join(names)} – {client}"[:200],
                     company_id=company.id if company else None, contact_id=contact.id if contact else None,
                     owner_id=int(data["owner_id"]) if data.get("owner_id") else user_id(),
                     due_on=_parse_date(data.get("due_on")), current_insurer=(data.get("current_insurer") or None),
                     current_premium=_parse_amount(data.get("current_premium"), "current_premium"),
                     current_rate=(str(data.get("current_rate") or "").strip()[:40] or None),
                     fields=clean_fields(names, data.get("fields")), notes=str(data.get("notes") or ""))
    case.stage = "info" if missing_fields(case) else "new"
    s.add(case)
    s.flush()
    event(s, case, "created", f"Dossier créé ({', '.join(names)})")
    return case


EDITABLE = ("title", "client_name", "company_id", "contact_id", "owner_id", "due_on",
            "current_insurer", "current_premium", "current_rate", "notes", "lost_reason")
_FIELD_LABELS = {"title": "intitulé", "branches": "branches", "client_name": "client", "company_id": "entreprise",
                 "contact_id": "interlocuteur", "owner_id": "responsable", "due_on": "date attendue",
                 "current_insurer": "assureur actuel", "current_premium": "prime actuelle",
                 "current_rate": "taux actuel", "lost_reason": "motif"}


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
            v = v.strip() or (None if k in ("current_insurer", "lost_reason", "current_rate") else "")
            if k == "current_rate" and v:
                v = v[:40]
        if k == "client_name" and not v:
            raise QuoteError({"client_name": "Indiquez le client."})
        if getattr(case, k) != v:
            setattr(case, k, v)
            changed.append(k)
    if "branches" in data or "branch" in data:
        names = _branch_list(data.get("branches")) or _branch_list(data.get("branch"))
        if not names:
            raise QuoteError({"branch": "Gardez au moins une branche."})
        if names != branches_of(case):
            _set_branches(s, case, names)
            changed.append("branches")
    if "fields" in data:
        new = {**(case.fields or {}), **clean_fields(branches_of(case), data["fields"])}
        for key, val in (data["fields"] or {}).items():  # champ vidé
            if val in (None, "") and key in new:
                new.pop(key)
        if new != (case.fields or {}):
            case.fields = new
            event(s, case, "fields", "Fiche de renseignements mise à jour")
    if "stage" in data and data["stage"] != case.stage:
        set_stage(s, case, str(data["stage"]), data.get("lost_reason"))
    if changed and changed != ["notes"]:
        event(s, case, "edit", "Dossier modifié : " + ", ".join(_FIELD_LABELS.get(k, k) for k in changed))
    return case


def _set_branches(s: Session, case: QuoteCase, names: list[str]) -> None:
    """Ajouter / retirer une branche. Une branche déjà envoyée à une compagnie ne se retire pas."""
    removed = set(branches_of(case)) - set(names)
    rows = list(s.scalars(select(QuoteInsurer).where(QuoteInsurer.case_id == case.id, QuoteInsurer.branch.in_(removed)))) if removed else []
    if any(r.status != "to_send" for r in rows):
        raise QuoteError({"branch": "Cette branche a déjà été envoyée à une compagnie : elle reste dans le dossier."})
    for r in rows:
        s.delete(r)
    added = [b for b in names if b not in branches_of(case)]
    case.branches, case.branch = names, names[0]
    # les compagnies déjà consultées le sont aussi pour la nouvelle branche (lignes « À envoyer »)
    for comp_id in dict.fromkeys(q.company_id for q in s.scalars(select(QuoteInsurer).where(QuoteInsurer.case_id == case.id))):
        if added:
            add_insurers(s, case, [comp_id], added, log=False)


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
    if case.stage in AUTO_STAGES and order.index(stage) > order.index(case.stage):
        set_stage(s, case, stage)


def _sync_offer_stage(s: Session, case: QuoteCase) -> None:
    """Première offre → « Offres partielles » ; toutes les compagnies du dossier ont répondu
    (offre, à renégocier ou refus) avec au moins une offre → « Toutes les offres reçues »."""
    s.flush()
    rows = list(s.scalars(select(QuoteInsurer).where(QuoteInsurer.case_id == case.id)))  # y compris « À envoyer »
    if not any(r.status in OFFER_STATUSES for r in rows):
        return
    _advance(s, case, "offers" if all(r.status in ANSWERED for r in rows) else "partial")


# --------------------------------------------------------------------------- compagnies

def company_contacts(s: Session, company_id: int) -> list[Contact]:
    """Les interlocuteurs d'une compagnie, service souscription d'abord."""
    order = {"souscription": 0, "production": 1}
    people = list(s.scalars(select(Contact).where(Contact.company_id == company_id,
                                                  Contact.global_status != "do_not_contact").order_by(Contact.id)))
    return sorted(people, key=lambda c: order.get(c.department or "", 2))


def default_contact(s: Session, company_id: int) -> Contact | None:
    people = company_contacts(s, company_id)
    return people[0] if people else None


def add_insurers(s: Session, case: QuoteCase, company_ids: list[int], names: list[str] | None = None,
                 log: bool = True) -> list[QuoteInsurer]:
    names = [b for b in (names or branches_of(case)) if b in branches_of(case)] or branches_of(case)
    have = {(qi.company_id, qi.branch) for qi in s.scalars(select(QuoteInsurer).where(QuoteInsurer.case_id == case.id))}
    added = []
    for cid in dict.fromkeys(int(x) for x in company_ids):
        comp = s.get(Company, cid)
        if comp is None:
            continue
        c = default_contact(s, cid)
        new = []
        for b in names:
            if (cid, b) in have:
                continue
            qi = QuoteInsurer(case_id=case.id, company_id=cid, branch=b, contact_id=c.id if c else None,
                              recipients=[c.email] if c else None)
            s.add(qi)
            new.append(qi)
        if new:
            s.flush()
            if log:
                event(s, case, "insurer", f"{comp.name} ajoutée aux compagnies à consulter"
                      + (f" ({', '.join(q.branch for q in new)})" if len(branches_of(case)) > 1 else ""), new[0])
            added += new
    return added


def rows_for(s: Session, case: QuoteCase, insurer_ids: list[int]) -> list[QuoteInsurer]:
    """Lignes d'un même envoi : même dossier, même compagnie."""
    rows = [r for r in (s.get(QuoteInsurer, int(i)) for i in dict.fromkeys(insurer_ids)) if r is not None and r.case_id == case.id]
    if not rows:
        raise QuoteError("Choisissez au moins une branche à envoyer.")
    if len({r.company_id for r in rows}) > 1:
        raise QuoteError("Un email ne s'adresse qu'à une compagnie.")
    order = branches_of(case)
    return sorted(rows, key=lambda r: order.index(r.branch) if r.branch in order else 99)


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


RENEGOTIATE_BODY = ('Bonjour {{ prenom | "Madame, Monsieur" }},\n\nMerci pour votre proposition concernant notre client '
                    "[Nom du client] ({branches}).\n\nAprès étude, notre client souhaiterait une révision de vos "
                    "conditions : [Points à renégocier : prime, franchise, garanties…].\n\nPourriez-vous nous adresser "
                    "une proposition révisée ?\n\nBien cordialement,")


def _greeting_contact(people: list[Contact]) -> Contact:
    """Contact « fictif » pour la formule d'appel : « Bonjour Nadia », « Bonjour Nadia et Sara »,
    ou la valeur de repli du modèle si un prénom manque."""
    names = [p.first_name.strip() for p in people if p.first_name and p.first_name.strip()]
    first = (" et ".join(names) if len(names) == len(people) and names else None)
    return Contact(email="", first_name=first)


def _render_vars(text: str, contact: Contact) -> str:
    ctx = render.RenderContext(contact=contact, signature="", target_blocks={}, sector_blocks={})
    return render.render(text, ctx).text


def _paras(text: str) -> list[str]:
    return [p.strip("\n") for p in re.split(r"\n\s*\n", text.strip()) if p.strip()]


def _combine(case: QuoteCase, bodies: dict[str, str]) -> str:
    """Un email commun pour plusieurs branches : formule d'appel et conclusion du 1er modèle, puis
    le détail de chaque branche (les paragraphes propres à la branche) sous son titre."""
    first = _paras(next(iter(bodies.values())))
    greeting = first[0] if first and first[0].lower().startswith("bonjour") else ""
    closing_idx = next((i for i, p in enumerate(first) if p.lower().startswith(("bien cordialement", "cordialement"))), len(first))
    ask = next((p for p in first if p.lower().startswith("merci")), "Merci de nous adresser votre meilleure proposition pour chacune de ces branches.")
    parts = [greeting] if greeting else []
    parts.append(f"Nous vous sollicitons pour une cotation au profit de notre client {case.client_name}, "
                 f"pour les branches suivantes : {', '.join(bodies)}.")
    for b, body in bodies.items():
        ps = _paras(body)
        end = next((i for i, p in enumerate(ps) if p.lower().startswith(("bien cordialement", "cordialement"))), len(ps))
        detail = [p for p in ps[:end] if not p.lower().startswith(("bonjour", "merci")) and case.client_name not in p
                  and f"[{CLIENT_PLACEHOLDER}]" not in p]
        parts.append(f"— {b} —\n" + "\n\n".join(detail) if detail else f"— {b} —")
    parts.append(ask)
    parts += first[closing_idx:] or ["Bien cordialement,"]
    return "\n\n".join(parts)


def _recipient_contacts(s: Session, emails: list[str]) -> list[Contact]:
    out = []
    for e in emails:
        c = s.scalars(select(Contact).where(Contact.email == e.strip().lower())).first()
        out.append(c or Contact(email=e.strip().lower()))
    return out


def draft(s: Session, case: QuoteCase, rows: list[QuoteInsurer], to: list[str] | None = None) -> dict:
    """Email prêt à relire pour une compagnie : demande (une ou plusieurs branches), relance ou
    renégociation (dans le même fil)."""
    comp = s.get(Company, rows[0].company_id)
    options = company_contacts(s, rows[0].company_id)
    recipients = [e.lower() for e in (to if to is not None else (rows[0].recipients or ([c.email for c in options[:1]])))]
    greet = _greeting_contact(_recipient_contacts(s, recipients))
    names = [r.branch for r in rows]
    followup = all(r.status != "to_send" and r.last_message_id for r in rows) and len({r.last_message_id for r in rows}) == 1
    reneg = followup and all(r.status == "renegotiate" for r in rows)
    if followup:
        lead = rows[0]
        subject = lead.first_subject or ""
        subject = subject if subject.lower().startswith("re:") else f"Re: {subject}"
        if reneg:
            body = fill(_render_vars(RENEGOTIATE_BODY.replace("{branches}", ", ".join(names)), greet), case, names[0])
        else:
            steps = template_steps(s, names[0])
            idx = min(1 + lead.reminders_sent, len(steps) - 1) if len(steps) > 1 else 0
            body = fill(_render_vars(steps[idx][1], greet), case, names[0])
        kind = "renegotiate" if reneg else "followup"
    else:
        bodies, subjects = {}, []
        for b in names:
            steps = template_steps(s, b)
            bodies[b] = fill(_render_vars(steps[0][1], greet), case, b)
            subjects.append(fill(_render_vars(steps[0][0], greet), case, b))
        if len(names) == 1:
            subject, body = subjects[0], bodies[names[0]]
        else:
            subject = f"Demande de cotation {' / '.join(names)} – {case.client_name}"
            body = _combine(case, bodies)
        kind = "request"
    files = list(s.execute(select(QuoteFile, Attachment).join(Attachment, Attachment.id == QuoteFile.attachment_id)
                           .where(QuoteFile.case_id == case.id, QuoteFile.kind.in_(("client", "current")))))
    return {"kind": kind, "followup": followup, "company": comp.name if comp else "", "company_id": rows[0].company_id,
            "insurer_ids": [r.id for r in rows], "branches": names,
            "to": recipients, "options": [{"id": c.id, "email": c.email, "department": c.department,
                                           "name": " ".join(x for x in [c.first_name, c.last_name] if x) or c.email}
                                          for c in options],
            "subject": subject, "body": body, "in_reply_to": rows[0].last_message_id if followup else None,
            "missing": render.placeholders(subject + "\n" + body),
            "attachments": [] if followup else [{"id": a.id, "name": a.filename, "size": a.size, "label": f.label,
                                                 "kind": f.kind, "checked": f.kind == "client"} for f, a in files]}


def send(s: Session, case: QuoteCase, rows: list[QuoteInsurer], body: dict, smtp_factory=None, imap_factory=None) -> list[QuoteInsurer]:
    from app import manual_mail
    d = manual_mail.draft_from(body)
    left = render.placeholders(d.subject + "\n" + d.body)
    if left:
        raise QuoteError({"body": "Champs encore à compléter : " + ", ".join(f"[{p}]" for p in left)})
    followup = all(r.status != "to_send" and r.last_message_id for r in rows) and len({r.last_message_id for r in rows}) == 1
    if followup:
        d.in_reply_to = rows[0].last_message_id
        d.references = [rows[0].last_message_id]
    out = manual_mail.send(s, d, smtp_factory=smtp_factory, imap_factory=imap_factory)  # commit inclus
    comp = s.get(Company, rows[0].company_id)
    now = utcnow()
    people = _recipient_contacts(s, d.to)
    for r in rows:
        if followup:
            r.reminders_sent += 1
            if r.status in ("sent", "reminded"):
                r.status = "reminded"
        else:
            r.status, r.sent_at, r.first_subject = "sent", now, d.subject
        r.sent_by, r.last_message_id, r.recipients = user_id(), out.message_id, d.to
        if people and people[0].id:
            r.contact_id = people[0].id
    reneg = followup and all(r.status == "renegotiate" for r in rows)
    what = "Renégociation" if reneg else "Relance" if followup else "Demande de cotation"
    event(s, case, "email_out", f"{what} envoyée à {comp.name if comp else ''}"
          + (f" – {', '.join(r.branch for r in rows)}" if len(branches_of(case)) > 1 else "")
          + f" ({', '.join(d.to)})" + (" – mode test" if out.test_mode else ""), rows[0],
          data={"subject": d.subject, "body": d.body[:6000], "to": d.to, "cc": d.cc, "attachments": out.attachments or [],
                "test_mode": out.test_mode, "insurer_ids": [r.id for r in rows], "branches": [r.branch for r in rows]},
          message_id=out.message_id)
    _close_reminders(s, case, rows[0].company_id)
    _schedule_followup(s, case, rows, comp)
    _advance(s, case, "consulting")
    s.commit()
    return rows


def send_all(s: Session, case: QuoteCase, company_ids: list[int] | None = None, smtp_factory=None, imap_factory=None) -> list[dict]:
    """Envoie d'un coup les demandes encore « À envoyer » : un email commun par compagnie (toutes
    ses branches), à ses destinataires habituels. Une compagnie sans destinataire ou dont l'email
    contient encore un [champ] à compléter est laissée de côté (raison dans le compte rendu)."""
    from app import manual_mail
    pending: dict[int, list[QuoteInsurer]] = {}
    for r in s.scalars(select(QuoteInsurer).where(QuoteInsurer.case_id == case.id, QuoteInsurer.status == "to_send")
                       .order_by(QuoteInsurer.id)):
        if company_ids is None or r.company_id in company_ids:
            pending.setdefault(r.company_id, []).append(r)
    report = []
    for cid, rows in pending.items():
        rows = rows_for(s, case, [r.id for r in rows])
        d = draft(s, case, rows)
        if not d["to"]:
            report.append({"company": d["company"], "ok": False, "reason": "Aucun destinataire (ajoutez un contact à la compagnie)."})
            continue
        if d["missing"]:
            report.append({"company": d["company"], "ok": False, "reason": "À compléter : " + ", ".join(f"[{p}]" for p in d["missing"])})
            continue
        try:
            send(s, case, rows, {"to": d["to"], "subject": d["subject"], "body": d["body"],
                                 "attachment_ids": [a["id"] for a in d["attachments"] if a["checked"]]},
                 smtp_factory=smtp_factory, imap_factory=imap_factory)
            report.append({"company": d["company"], "ok": True, "to": d["to"]})
        except (manual_mail.SendRefused, QuoteError) as exc:
            s.rollback()
            report.append({"company": d["company"], "ok": False, "reason": str(exc) or "Envoi refusé."})
    return report


def _schedule_followup(s: Session, case: QuoteCase, rows: list[QuoteInsurer], comp: Company | None) -> Reminder:
    from app.scheduling import SendWindow
    days = int(settings_store.get(s, "quote_followup_days") or 4)
    due = SendWindow.from_settings(s).add_days(to_local(utcnow()).date(), days, True)
    r = Reminder(kind="quote", title=f"Relancer {comp.name if comp else 'la compagnie'} · {case.client_name} ({case.ref})"[:255],
                 notes=f"Dossier {case.ref} – {', '.join(x.branch for x in rows)}. Sans réponse : relance proposée depuis le dossier.",
                 due_on=due, company_id=rows[0].company_id, user_id=user_id(), quote_case_id=case.id)
    s.add(r)
    return r


def _close_reminders(s: Session, case: QuoteCase, company_id: int | None = None) -> int:
    """Clôt les rappels de relance ouverts du dossier (de toute l'équipe : le dossier est commun).
    Sans compagnie (dossier gagné ou perdu) : tous les rappels du dossier."""
    q = select(Reminder).where(Reminder.quote_case_id == case.id, Reminder.done_at.is_(None))
    if company_id is not None:
        q = q.where(Reminder.company_id == company_id, Reminder.kind == "quote")
    n = 0
    for r in s.scalars(q.execution_options(oddo_all=True)):  # rappels de tous les employés : dossier commun
        r.done_at = utcnow()
        n += 1
    return n


def set_insurer(s: Session, case: QuoteCase, qi: QuoteInsurer, data: dict) -> QuoteInsurer:
    comp = s.get(Company, qi.company_id)
    if "recipients" in data:
        qi.recipients = [str(e).strip().lower() for e in data["recipients"] or [] if str(e).strip()] or None
    if "offer_premium" in data:
        qi.offer_premium = _parse_amount(data["offer_premium"], "offer_premium")
    if "offer_rate" in data:
        qi.offer_rate = (str(data["offer_rate"] or "").strip()[:40] or None)
    if "notes" in data:
        qi.notes = str(data["notes"] or "")
    if "status" in data and data["status"] != qi.status:
        st = str(data["status"])
        if st not in INSURER_LABELS:
            raise QuoteError({"status": "Statut inconnu."})
        qi.status = st
        if st in ("replied",) + ANSWERED:
            qi.replied_at = qi.replied_at or utcnow()
            _close_reminders(s, case, qi.company_id)
        multi = len(branches_of(case)) > 1
        event(s, case, "insurer", f"{comp.name if comp else 'Compagnie'}{f' ({qi.branch})' if multi else ''} : {INSURER_LABELS[st]}"
              + (f" – {_fmt_number(qi.offer_premium)} MAD" if st in OFFER_STATUSES and qi.offer_premium else ""), qi)
        if st in ANSWERED:
            _sync_offer_stage(s, case)
    return qi


def remove_insurer(s: Session, case: QuoteCase, qi: QuoteInsurer) -> None:
    if qi.status != "to_send":
        raise QuoteError("Cette compagnie a déjà été consultée : marquez plutôt « Refus » ou laissez-la dans le dossier.")
    comp = s.get(Company, qi.company_id)
    event(s, case, "insurer", f"{comp.name if comp else 'Compagnie'} retirée du dossier"
          + (f" ({qi.branch})" if len(branches_of(case)) > 1 else ""))
    s.delete(qi)


# --------------------------------------------------------------------------- rappels

def add_reminder(s: Session, case: QuoteCase, data: dict) -> Reminder:
    title = " ".join(str(data.get("title") or "").split())
    if not title:
        raise QuoteError({"title": "Indiquez ce qu'il faut faire."})
    due = _parse_date(data.get("due_on"), "due_on")
    if due is None:
        raise QuoteError({"due_on": "Choisissez la date."})
    t = (data.get("due_time") or "").strip() or None
    if t:
        try:
            t = time.fromisoformat(t).strftime("%H:%M")
        except ValueError:
            raise QuoteError({"due_time": "Heure invalide (HH:MM)."}) from None
    kind = data.get("kind") or "other"
    if kind not in REMINDER_KINDS:
        kind = "other"
    r = Reminder(kind=kind, title=title[:255], notes=str(data.get("notes") or ""), due_on=due, due_time=t,
                 company_id=case.company_id, contact_id=case.contact_id, user_id=user_id(), quote_case_id=case.id)
    s.add(r)
    event(s, case, "note", f"Rappel ajouté : {title} ({due.strftime('%d/%m/%Y')}{f' à {t}' if t else ''})")
    return r


# --------------------------------------------------------------------------- documents

def add_file(s: Session, case: QuoteCase, attachment_id: int, kind: str = "client", label: str = "",
             insurer_id: int | None = None) -> QuoteFile:
    att = s.get(Attachment, attachment_id)
    if att is None:
        raise QuoteError({"file": "Fichier introuvable."})
    if kind not in QUOTE_FILE_KINDS:
        kind = "other"
    qi = s.get(QuoteInsurer, insurer_id) if insurer_id else None
    if qi is not None and qi.case_id != case.id:
        qi = None
    f = QuoteFile(case_id=case.id, attachment_id=att.id, kind=kind, label=str(label or "")[:120],
                  insurer_id=qi.id if qi else None)
    s.add(f)
    s.flush()
    comp = s.get(Company, qi.company_id) if qi else None
    what = {"current": "Conditions actuelles", "offer": "Offre", "client": "Pièce du client"}.get(kind, "Document")
    event(s, case, "file", f"{what} ajouté{'e' if kind in ('offer', 'client') else 's' if kind == 'current' else ''} : {att.filename}"
          + (f" ({comp.name})" if comp and kind == "offer" else ""), qi, data={"file_id": f.id, "name": att.filename})
    if kind == "offer" and qi is not None and qi.status not in OFFER_STATUSES:
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
    rows = [r for r in (s.get(QuoteInsurer, i) for i in ((sent.data or {}).get("insurer_ids") or [sent.insurer_id])) if r is not None]
    if case is None or not rows:
        return False
    names = []  # pièces jointes : nom + position dans l'email (pour « Ranger comme offre »)
    try:
        from app.mailbox_browser import _leaves, _part_name
        msg = message_from_bytes(raw, policy=policy.default)
        names = [{"name": _part_name(p, i), "index": i} for i, p in enumerate(_leaves(msg))
                 if p.get_filename() or p.get_content_disposition() == "attachment"][:20]
    except Exception:  # noqa: BLE001 – une pièce jointe illisible n'empêche pas le rattachement
        pass
    comp = s.get(Company, rows[0].company_id)
    auto = a.kind == "auto_reply"
    event(s, case, "email_in", f"{'Réponse automatique' if auto else 'Réponse'} de {comp.name if comp else a.sender}"
          f" ({a.sender})", rows[0], message_id=a.message_id,
          data={"subject": a.subject[:500], "body": (a.text or "")[:6000], "from": a.sender,
                "received_at": a.received_at.isoformat() if a.received_at else None, "folder": folder, "uid": uid,
                "mailbox_id": mailbox_id, "attachments": names, "auto_reply": auto, "insurer_ids": [r.id for r in rows]})
    if not auto:
        for r in rows:
            if r.status in ("sent", "reminded"):
                r.status, r.replied_at = "replied", utcnow()
        _close_reminders(s, case, rows[0].company_id)
    return True


# --------------------------------------------------------------------------- JSON

def _user_names(s: Session) -> dict[int, str]:
    from app.models import AppUser
    return {u.id: (u.full_name or u.email) for u in s.scalars(select(AppUser))}


def summary_json(case: QuoteCase, insurers: list[QuoteInsurer], users: dict[int, str]) -> dict:
    today = to_local(utcnow()).date()
    comps: dict[int, list[QuoteInsurer]] = {}
    for qi in insurers:
        comps.setdefault(qi.company_id, []).append(qi)
    # par compagnie : la plus avancée de ses lignes (une offre sur une branche compte comme offre)
    rank = ["to_send", "sent", "reminded", "replied", "declined", "renegotiate", "offer"]
    counts = {k: 0 for k in INSURER_LABELS}
    for rows in comps.values():
        counts[max((r.status for r in rows), key=rank.index)] += 1
    names = branches_of(case)
    return {"id": case.id, "ref": case.ref, "title": case.title, "branch": case.branch, "branches": names,
            "branch_label": " + ".join(names), "stage": case.stage,
            "client_name": case.client_name, "company_id": case.company_id, "contact_id": case.contact_id,
            "owner_id": case.owner_id, "owner_name": users.get(case.owner_id) if case.owner_id else None,
            "due_on": case.due_on.isoformat() if case.due_on else None,
            "late": bool(case.due_on and case.due_on < today and case.stage in OPEN_STAGES),
            "missing": len(missing_fields(case)), "insurers": len(comps), "insurer_counts": counts,
            "best_offer": min((qi.offer_premium for qi in insurers if qi.status in OFFER_STATUSES and qi.offer_premium), default=None)
            if len(names) == 1 else None,
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


def _person(c: Contact | None) -> dict | None:
    if c is None:
        return None
    return {"id": c.id, "email": c.email, "name": " ".join(x for x in [c.first_name, c.last_name] if x) or c.email,
            "department": c.department}


def detail_json(s: Session, case: QuoteCase) -> dict:
    from app.attachments_service import as_json as att_json
    from app.mailbox_service import get_primary
    users = _user_names(s)
    names = branches_of(case)
    order = {b: i for i, b in enumerate(names)}
    insurers = sorted(s.scalars(select(QuoteInsurer).where(QuoteInsurer.case_id == case.id).order_by(QuoteInsurer.id)),
                      key=lambda q: order.get(q.branch, 99))
    comp_ids = list(dict.fromkeys(qi.company_id for qi in sorted(insurers, key=lambda q: q.id)))
    comps = {c.id: c for c in s.scalars(select(Company).where(Company.id.in_(comp_ids + ([case.company_id] if case.company_id else []))))}
    contact = s.get(Contact, case.contact_id) if case.contact_id else None
    files = list(s.execute(select(QuoteFile, Attachment).join(Attachment, Attachment.id == QuoteFile.attachment_id)
                           .where(QuoteFile.case_id == case.id).order_by(QuoteFile.id)))
    events = list(s.scalars(select(QuoteEvent).where(QuoteEvent.case_id == case.id).order_by(QuoteEvent.ts.desc(), QuoteEvent.id.desc())))
    reminders = list(s.scalars(select(Reminder).where(Reminder.quote_case_id == case.id)
                               .order_by(Reminder.done_at.is_not(None), Reminder.due_on, Reminder.due_time)
                               .execution_options(oddo_all=True)))  # rappels de toute l'équipe sur ce dossier
    me = user_id()
    mb = get_primary(s)
    my_box = mb.id if mb else None
    docs = list(dict.fromkeys(d for b in names for d in branch_def(b)["docs"]))
    return {**summary_json(case, insurers, users),
            "fields": case.fields or {}, "notes": case.notes, "current_insurer": case.current_insurer,
            "current_rate": case.current_rate,
            "closed_at": case.closed_at.isoformat() if case.closed_at else None,
            "field_defs": field_defs(names), "docs": docs, "missing_labels": missing_fields(case),
            "all_branches": [b["name"] for b in branches()],
            "company": {"id": comps[case.company_id].id, "name": comps[case.company_id].name} if case.company_id in comps else None,
            "contact": _person(contact),
            "companies": [{
                "company_id": cid, "company": comps[cid].name if cid in comps else "?",
                "logo": f"/api/companies/{cid}/logo?v={comps[cid].logo}" if cid in comps and comps[cid].logo else None,
                "contacts": [_person(c) for c in company_contacts(s, cid)],
                "rows": [{"id": qi.id, "branch": qi.branch, "status": qi.status, "recipients": qi.recipients or [],
                          "sent_at": qi.sent_at.isoformat() if qi.sent_at else None,
                          "replied_at": qi.replied_at.isoformat() if qi.replied_at else None,
                          "reminders_sent": qi.reminders_sent, "offer_premium": qi.offer_premium,
                          "offer_rate": qi.offer_rate, "notes": qi.notes, "last_message_id": qi.last_message_id,
                          "sent_by_name": users.get(qi.sent_by) if qi.sent_by else None}
                         for qi in insurers if qi.company_id == cid],
            } for cid in comp_ids],
            "files": [{**att_json(a), "file_id": f.id, "kind": f.kind, "label": f.label, "insurer_id": f.insurer_id,
                       "created_at": f.created_at.isoformat()} for f, a in files],
            "reminders": [{"id": r.id, "title": r.title, "kind": r.kind, "due_on": r.due_on.isoformat(), "due_time": r.due_time,
                           "done": r.done_at is not None, "notes": r.notes or "", "mine": r.user_id == me,
                           "user_name": users.get(r.user_id) if r.user_id else None} for r in reminders],
            "events": [{"id": e.id, "kind": e.kind, "text": e.text, "data": e.data, "insurer_id": e.insurer_id,
                        "user_name": users.get(e.user_id) if e.user_id else None, "ts": e.ts.isoformat(),
                        "mine": bool(e.data and my_box is not None and e.data.get("mailbox_id") == my_box)}
                       for e in events[:200]]}

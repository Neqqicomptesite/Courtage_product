"""Export Excel des résultats (§6.10) : feuilles Contacts, Réponses, Synthèse.

Excel ne connaît pas les fuseaux horaires : toutes les dates sont converties en
heure du Maroc puis écrites « sans fuseau », pour s'afficher telles quelles.
"""
from __future__ import annotations

import io
from datetime import datetime

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import settings_store, stats
from app.companies_service import KIND_LABELS as CONTACT_KINDS
from app.contacts_service import STATUS_LABELS, reliability_category
from app.campaigns_service import ENROLLMENT_LABELS
from app.models import Campaign, Contact, Enrollment, Message
from app.replies_service import CLASSES
from app.timeutil import to_local

HEADER_FILL = PatternFill("solid", fgColor="1F4E79")
HEADER_FONT = Font(bold=True, color="FFFFFF")
KIND_LABELS = {"reply": "Réponse", "auto_reply": "Absence", "unsubscribe": "Désinscription (STOP)",
               "bounce_hard": "Rebond définitif", "bounce_soft": "Rebond temporaire", "unmatched": "Non rattachée"}


def _local(dt: datetime | None):
    return to_local(dt).replace(tzinfo=None) if dt else None


def _sheet(wb: Workbook, title: str, headers: list[str], rows: list[list], widths: dict[int, int] | None = None):
    ws = wb.create_sheet(title)
    ws.append(headers)
    for cell in ws[1]:
        cell.fill, cell.font = HEADER_FILL, HEADER_FONT
        cell.alignment = Alignment(vertical="center", wrap_text=True)
    for r in rows:
        ws.append(r)
    ws.freeze_panes = "A2"
    if rows:
        ws.auto_filter.ref = ws.dimensions
    for i, h in enumerate(headers, start=1):
        ws.column_dimensions[get_column_letter(i)].width = (widths or {}).get(i, min(max(len(h) + 2, 12), 40))
    for row in ws.iter_rows(min_row=2):
        for c in row:
            if isinstance(c.value, datetime):
                c.number_format = "dd/mm/yyyy hh:mm"
    return ws


def build(s: Session, campaign_id: int | None = None) -> bytes:
    wb = Workbook()
    wb.remove(wb.active)
    labels = settings_store.get(s, "custom_field_labels")

    # ------------------------------------------------------------- Contacts
    if campaign_id:
        pairs = list(s.execute(select(Contact, Enrollment).join(Enrollment, Enrollment.contact_id == Contact.id)
                               .where(Enrollment.campaign_id == campaign_id).order_by(Contact.company)))
    else:
        # Export global : une ligne par contact, avec sa dernière inscription s'il en a une.
        latest = {}
        for e in s.scalars(select(Enrollment).order_by(Enrollment.created_at)):
            latest[e.contact_id] = e
        pairs = [(c, latest.get(c.id)) for c in s.scalars(select(Contact).order_by(Contact.company))]
    camps = {c.id: c.name for c in s.scalars(select(Campaign))}
    custom_keys = sorted({k for c, _ in pairs for k in (c.custom or {})})
    headers = ["Prénom", "Nom", "Email", "Entreprise", "Type de contact", "Poste", "Secteur", "Famille de secteur", "Cible",
               "Code séquence", "Taille", "Vague", "Fiabilité", "Fiabilité (détail)", "Téléphone", "Site web",
               "LinkedIn", "Source", *[labels.get(k, k) for k in custom_keys], "Statut global", "Campagne",
               "Variante", "Statut dans la campagne", "Étape atteinte", "Dernier envoi", "Date de réponse",
               "Classement", "Notes"]
    rows = []
    for c, e in pairs:
        last_sent = reply_at = classification = None
        if e is not None:
            last_sent = s.scalar(select(func.max(Message.sent_at)).where(Message.enrollment_id == e.id,
                                                                        Message.direction == "out"))
            reply = s.scalars(select(Message).where(Message.enrollment_id == e.id, Message.direction == "in",
                                                    Message.kind.in_(("reply", "unsubscribe")))
                              .order_by(Message.received_at)).first()
            if reply:
                reply_at, classification = reply.received_at, CLASSES.get(reply.classification or "", "Non classée")
        steps_sent = s.scalar(select(func.max(Message.step_position)).where(
            Message.enrollment_id == e.id, Message.direction == "out", Message.sent_at.is_not(None))) if e else None
        rows.append([c.first_name, c.last_name, c.email, c.company, CONTACT_KINDS.get(c.kind), c.job_title, c.sector, c.sector_family,
                     c.target_segment, c.sequence_code, c.size_bucket, c.wave, reliability_category(c.email_reliability),
                     c.email_reliability, c.phone, c.website, c.linkedin_url, c.source,
                     *[(c.custom or {}).get(k) for k in custom_keys], STATUS_LABELS.get(c.global_status),
                     camps.get(e.campaign_id) if e else None, e.variant_label if e else None,
                     ENROLLMENT_LABELS.get(e.status) if e else None, steps_sent, _local(last_sent),
                     _local(reply_at), classification, c.notes or None])
    _sheet(wb, "Contacts", headers, rows)

    # ------------------------------------------------------------- Réponses
    q = (select(Message, Contact).join(Contact, Contact.id == Message.contact_id)
         .where(Message.direction == "in"))
    if campaign_id:
        q = q.join(Enrollment, Enrollment.id == Message.enrollment_id).where(Enrollment.campaign_id == campaign_id)
    replies = [[f"{c.first_name or ''} {c.last_name or ''}".strip(), c.email, c.company, c.sequence_code,
                _local(m.received_at), KIND_LABELS.get(m.kind, m.kind), m.subject, m.body_text,
                CLASSES.get(m.classification or "", "Non classée"), m.callback_on, m.note,
                "oui" if m.test_mode else ""]
               for m, c in s.execute(q.order_by(Message.received_at))]
    ws = _sheet(wb, "Réponses", ["Contact", "Email", "Entreprise", "Code séquence", "Date", "Type", "Objet",
                                 "Texte (sans citation)", "Classement", "Rappel le", "Note", "Mode test"],
                replies, widths={7: 35, 8: 70, 11: 30})
    for row in ws.iter_rows(min_row=2, min_col=8, max_col=8):
        for cell in row:
            cell.alignment = Alignment(wrap_text=True, vertical="top")

    # ------------------------------------------------------------- Synthèse
    ind = stats.indicators(s, campaign_id)
    ws = wb.create_sheet("Synthèse")
    title = f"Campagne : {camps.get(campaign_id)}" if campaign_id else "Toutes les campagnes"
    ws.append([title])
    ws["A1"].font = Font(bold=True, size=13)
    ws.append([])
    for label, value in [("Contacts inscrits", ind.enrolled), ("Contacts ayant reçu au moins 1 email", ind.reached),
                         *[(f"Emails envoyés – étape {k}", v) for k, v in ind.sent_by_step.items()],
                         ("Réponses", ind.replies),
                         ("Taux de réponse", ind.reply_rate if ind.reply_rate is not None else "—"),
                         ("Intéressés", ind.interested), ("Rebonds", ind.bounced),
                         ("Désinscriptions", ind.unsubscribed), ("Absences", ind.out_of_office),
                         ("Terminés sans réponse", ind.completed_no_reply)]:
        ws.append([label, value])
        if label == "Taux de réponse" and isinstance(value, float):
            ws.cell(ws.max_row, 2).number_format = "0.0%"
    ws.append([])
    ws.append(["Par segment (cible × secteur)", "Touchés", "Réponses", "Taux"])
    for c in ws[ws.max_row]:
        c.font = Font(bold=True)
    for r in stats.by_segment(s, campaign_id):
        ws.append([r.key, r.reached, r.replies, r.rate])
        ws.cell(ws.max_row, 4).number_format = "0.0%"
    ab_rows, too_small = stats.ab_test(s, campaign_id)
    if ab_rows:
        ws.append([])
        ws.append(["Test A/B (objet de l'étape 1)", "Contacts", "Réponses", "Taux"])
        for c in ws[ws.max_row]:
            c.font = Font(bold=True)
        for r in ab_rows:
            ws.append([f"Variante {r.key}", r.reached, r.replies, r.rate])
            ws.cell(ws.max_row, 4).number_format = "0.0%"
        if too_small:
            ws.append(["Échantillon trop petit pour conclure avec certitude"])
    ws.column_dimensions["A"].width = 42
    for col in "BCD":
        ws.column_dimensions[col].width = 12
    wb.move_sheet("Synthèse", offset=-2)

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()

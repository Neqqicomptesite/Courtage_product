"""API V2 : contacts, fiche contact, import, liste d'exclusion."""
from __future__ import annotations

import json
import secrets
from pathlib import Path

from fastapi import APIRouter, HTTPException, Response, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from app import contacts_service as cs
from app import campaigns_service as camp_svc
from app import importer, settings_store, suppression, template_xlsx, vocab
from app.db import get_session
from app.models import Company, Contact, Suppression
from app.timeutil import fmt_local, utcnow
from app.web.api_common import contact_ref, iso, not_found, require_admin_or_owner
from app.web.routes_contacts import MANUAL_REASON, MAX_UPLOAD, TOKEN_RE, _discard, _imports_dir, _upload

router = APIRouter(prefix="/api")


def _owners(s) -> dict[int, str]:
    """V3 : noms des employés (pour « Suivi par »), lus une fois par requête."""
    from app.models import AppUser
    return {u.id: (u.full_name or u.email) for u in s.scalars(select(AppUser))}


def _owner(c: Contact, names: dict[int, str] | None) -> dict | None:
    from app.current import user_id
    if not c.owner_id:
        return None
    return {"id": c.owner_id, "name": (names or {}).get(c.owner_id, "un collègue"), "me": c.owner_id == user_id()}


def _row(c: Contact, names: dict[int, str] | None = None) -> dict:
    return {**contact_ref(c), "job_title": c.job_title, "wave": c.wave, "status": c.global_status, "owner": _owner(c, names),
            "reliability": cs.reliability_category(c.email_reliability), "sector_family": c.sector_family,
            "target_segment": c.target_segment, "kind": c.kind, "company_id": c.company_id,
            "department": c.department, "seniority": c.seniority}


def _filters(params: dict) -> cs.ContactFilters:
    return cs.ContactFilters(**{k: (params.get(k) or "").strip() for k in cs.ContactFilters.__dataclass_fields__})


@router.get("/contacts")
def contacts(q: str = "", target_segment: str = "", sector_family: str = "", sequence_code: str = "",
             wave: str = "", reliability: str = "", status: str = "", campaign_id: str = "", kind: str = "",
             company_id: str = "", department: str = "", seniority: str = "", owner: str = ""):
    f = _filters(locals())
    with get_session() as s:
        names = _owners(s)
        rows = [_row(c, names) for c in s.scalars(cs.filtered_query(f))]
        opts = cs.filter_options(s)
        return {"total": cs.count_all(s), "items": rows,
                "options": {**{k: v for k, v in opts.items() if k not in ("status", "campaigns")},
                            "status": [{"value": k, "label": v} for k, v in opts["status"]],
                            "campaigns": [{"value": str(i), "label": n} for i, n in opts["campaigns"]]},
                "vocab": vocab.options(),
                # V2.7 : cartes du haut (Assureurs, Clients, Prospects, Partenaires)
                "kind_counts": dict(s.execute(select(Contact.kind, func.count(Contact.id)).group_by(Contact.kind)).all()),
                "companies": sorted({c for c in s.scalars(select(Company.name))}, key=str.lower),
                # pour que le formulaire montre le type hérité (« Sanlam » -> Assureur) avant l'enregistrement
                "company_kinds": dict(s.execute(select(Company.name, Company.kind).where(Company.kind != "prospect")).all())}


@router.get("/contacts/template")
def contacts_template():
    """Modèle Excel vierge, aux en-têtes reconnus automatiquement par l'import."""
    return Response(template_xlsx.build(),
                    media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": 'attachment; filename="Modele_contacts_ODDO.xlsx"',
                             "Cache-Control": "no-store"})


def _invalid(exc: cs.ContactInvalid) -> HTTPException:
    detail = {"errors": exc.errors}
    if exc.existing_id:
        detail["existing_id"] = exc.existing_id
    return HTTPException(409 if exc.existing_id else 422, detail)


@router.post("/contacts")
def contact_create(body: dict):
    with get_session() as s:
        try:
            c, warnings = cs.create_contact(s, body, f"Saisie manuelle – {fmt_local(utcnow())}")
        except cs.ContactInvalid as exc:
            s.rollback()
            raise _invalid(exc) from None
        s.commit()
        return {"id": c.id, "warnings": warnings}


@router.put("/contacts/{cid:int}")
def contact_update(cid: int, body: dict):
    with get_session() as s:
        c = s.get(Contact, cid)
        if c is None:
            raise not_found("Contact")
        try:
            changed = cs.update_contact(s, c, body)
        except cs.ContactInvalid as exc:
            s.rollback()
            raise _invalid(exc) from None
        s.commit()
        return {"changed": changed}


@router.get("/contacts/count")
def contacts_count(target_segment: str = "", sector_family: str = "", sequence_code: str = "",
                   wave: str = "", reliability: str = "", kind: str = "", category: str = "prospection",
                   contact_ids: str = ""):
    """Compteur en direct pour l'assistant de campagne (« 54 contacts correspondent »).
    En prospection, seuls les prospects comptent ; en gestion/souscription (V2.8), tous les types."""
    f = _filters({k: v for k, v in locals().items() if k not in ("category", "contact_ids")})
    with get_session() as s:
        q = cs.filtered_query(f)
        ids = camp_svc.parse_ids(contact_ids)  # V2.10 : sélection à la main
        if ids is not None:
            q = q.where(Contact.id.in_(ids))
        total = s.scalar(select(func.count()).select_from(q.subquery())) or 0
        prospection = category == "prospection"
        active_q = q.where(Contact.global_status == "active")
        if prospection:
            active_q = active_q.where(Contact.kind == "prospect")
        active = s.scalar(select(func.count()).select_from(active_q.subquery())) or 0
        protected = (s.scalar(select(func.count()).select_from(q.where(Contact.kind != "prospect").subquery())) or 0) if prospection else 0
        return {"matching": total, "active": active, "protected": protected}


@router.get("/contacts/{cid:int}")
def contact_detail(cid: int):
    with get_session() as s:
        c = s.get(Contact, cid)
        if c is None:
            raise not_found("Contact")
        labels = settings_store.get(s, "custom_field_labels")
        return {
            **_row(c, _owners(s)),
            "sector": c.sector, "size_bucket": c.size_bucket, "website": c.website, "linkedin_url": c.linkedin_url,
            "email_reliability_detail": c.email_reliability, "source": c.source, "notes": c.notes,
            "custom": [{"key": k, "label": labels.get(k, k.replace("_", " ").capitalize()), "value": v}
                       for k, v in (c.custom or {}).items()],
            "suppressed": suppression.is_suppressed_db(s, c.email),
            "status_label": cs.STATUS_LABELS[c.global_status],
            "company_ref": ({"id": c.company_id, "name": comp.name, "kind": comp.kind}
                            if c.company_id and (comp := s.get(Company, c.company_id)) else None),
            "enrollments": [{"id": e.id, "campaign": {"id": camp.id, "name": camp.name}, "status": e.status,
                             "step": e.current_step, "next_due_at": iso(e.next_due_at),
                             "active": e.status in cs.ACTIVE_ENROLLMENT}
                            for e, camp in cs.enrollments_of(s, c)],
            "timeline": [{"ts": iso(t.ts), "kind": t.kind, "title": t.title, "detail": t.detail}
                         for t in cs.timeline(s, c)],
        }


class OwnerIn(BaseModel):
    contact_ids: list[int] = Field(min_length=1, max_length=5000)
    owner_id: int | None = None   # None : plus de responsable (le prospect redevient libre)


@router.post("/contacts/owner")
def contacts_set_owner(body: OwnerIn):
    """V3 : l'administrateur attribue des prospects à un employé (ou les libère). Les campagnes
    déjà en cours ne bougent pas : elles restent dans la boîte de l'employé qui les a lancées."""
    from app.models import AppUser
    require_admin_or_owner(None, "Attribuer des contacts est réservé à l'administrateur.")
    with get_session() as s:
        if body.owner_id is not None:
            u = s.get(AppUser, body.owner_id)
            if u is None or not u.active:
                raise HTTPException(404, "Employé introuvable ou désactivé.")
        n = 0
        for c in s.scalars(select(Contact).where(Contact.id.in_(body.contact_ids))):
            c.owner_id = body.owner_id
            n += 1
        s.commit()
        return {"updated": n}


class NotesIn(BaseModel):
    notes: str


@router.put("/contacts/{cid:int}/notes")
def contact_notes(cid: int, body: NotesIn):
    with get_session() as s:
        c = s.get(Contact, cid)
        if c is None:
            raise not_found("Contact")
        c.notes = body.notes.replace("\r\n", "\n").strip()
        s.commit()
    return {"ok": True}


class EraseIn(BaseModel):
    confirm: str


@router.post("/contacts/{cid:int}/erase")
def contact_erase(cid: int, body: EraseIn):
    if body.confirm.strip().upper() != "EFFACER":
        raise HTTPException(400, "Tapez EFFACER pour confirmer l'effacement définitif.")
    with get_session() as s:
        c = s.get(Contact, cid)
        if c is None:
            raise not_found("Contact")
        require_admin_or_owner(c.owner_id, "Effacer un contact est réservé à son responsable ou à l'administrateur.")
        cs.erase(s, c)
        s.commit()
    return {"ok": True}


@router.post("/contacts/{cid:int}/enrollments/{eid:int}/remove")
def contact_remove(cid: int, eid: int):
    with get_session() as s:
        c = s.get(Contact, cid)
        if c is None:
            raise not_found("Contact")
        ok = cs.remove_from_campaign(s, c, eid)
        s.commit()
    return {"ok": ok}


# Route générique déclarée APRÈS /erase : FastAPI essaie les routes dans l'ordre.
@router.post("/contacts/{cid:int}/{action}")
def contact_action(cid: int, action: str):
    with get_session() as s:
        c = s.get(Contact, cid)
        if c is None:
            raise not_found("Contact")
        if action == "do-not-contact":
            cs.set_do_not_contact(s, c)
        elif action == "reactivate":
            if c.owner_id is not None:
                require_admin_or_owner(c.owner_id, "Seul le responsable de ce contact (ou l'administrateur) peut le réactiver.")
            try:
                cs.reactivate(s, c)
            except cs.ReactivationRefused as exc:
                raise HTTPException(409, str(exc)) from None
        else:
            raise HTTPException(404)
        s.commit()
    return {"ok": True}


# ---------------------------------------------------------------------- import

def _columns(table: importer.Table) -> list[dict]:
    mapping = importer.auto_mapping(table.headers)
    out = []
    for i, (h, m) in enumerate(zip(table.headers, mapping)):
        samples = [r[i].value or r[i].link for r in table.rows[:3] if r[i].value or r[i].link]
        out.append({"index": i, "header": h, "mapping": m, "custom": f"custom:{importer.slug(h)}", "samples": samples})
    return out


@router.post("/import")
async def import_upload(file: UploadFile):
    name = Path(file.filename or "").name
    ext = Path(name).suffix.lower()
    if ext not in (".xlsx", ".xlsm", ".csv"):
        raise HTTPException(400, "Format non pris en charge : choisissez un fichier .xlsx ou .csv.")
    data = await file.read(MAX_UPLOAD + 1)
    if len(data) > MAX_UPLOAD:
        raise HTTPException(400, "Fichier trop volumineux (10 Mo maximum).")
    token = secrets.token_hex(8)
    (_imports_dir() / f"{token}{ext}").write_bytes(data)
    (_imports_dir() / f"{token}.json").write_text(json.dumps({"filename": name, "ext": ext}, ensure_ascii=False),
                                                  encoding="utf-8")
    try:
        importer.read_table(_imports_dir() / f"{token}{ext}")
    except Exception as exc:  # noqa: BLE001
        _discard(token)
        raise HTTPException(400, f"Fichier illisible : {exc}") from None
    return import_columns(token)


@router.get("/import/{token}")
def import_columns(token: str, sheet: str | None = None):
    path, meta = _upload(token)
    table = importer.read_table(path, sheet)
    return {"token": token, "filename": meta["filename"], "sheets": table.sheets, "sheet": table.sheet,
            "header_row": table.header_row, "rows": len(table.rows), "columns": _columns(table),
            "fields": [{"value": f"field:{f}", "label": label} for f, label in importer.CONTACT_FIELDS]}


class MappingIn(BaseModel):
    sheet: str | None = None
    mapping: list[str]


def _plan(token: str, body: MappingIn):
    path, meta = _upload(token)
    table = importer.read_table(path, body.sheet)
    if len(body.mapping) != len(table.headers):
        raise HTTPException(400, "Correspondance incomplète.")
    errors = importer.validate_mapping(body.mapping)
    if errors:
        raise HTTPException(422, " ".join(errors))
    return meta, table


@router.post("/import/{token}/preview")
def import_preview(token: str, body: MappingIn):
    _, table = _plan(token, body)
    with get_session() as s:
        plan = importer.plan_import(s, table, body.mapping)
    row = lambda r: {"row": r.row_no, "email": r.email, "reason": r.reason, "warnings": r.warnings}  # noqa: E731
    return {"new": len(plan.of("new")), "update": len(plan.of("update")),
            "ignored": [row(r) for r in plan.of("ignore")], "suppressed": [row(r) for r in plan.suppressed],
            "warnings": [row(r) for r in plan.warned]}


@router.post("/import/{token}/commit")
def import_commit(token: str, body: MappingIn):
    meta, table = _plan(token, body)
    source = f"{meta['filename']} – importé le {fmt_local(utcnow())}"
    with get_session() as s:
        counts = importer.apply_plan(s, importer.plan_import(s, table, body.mapping), source)
        s.commit()
    _discard(token)
    return counts


@router.delete("/import/{token}")
def import_cancel(token: str):
    if TOKEN_RE.match(token):
        _discard(token)
    return {"ok": True}


# ------------------------------------------------------------ liste d'exclusion

@router.get("/exclusions")
def exclusions():
    with get_session() as s:
        rows = s.scalars(select(Suppression).order_by(Suppression.created_at.desc()))
        return [{"id": r.id, "value": r.email_or_domain, "reason": r.reason, "created_at": iso(r.created_at),
                 "kind": "hash" if r.email_or_domain.startswith(suppression.HASH_PREFIX)
                 else "domain" if r.email_or_domain.startswith("@") else "email",
                 "removable": r.reason.startswith(MANUAL_REASON)} for r in rows]


class ExclusionIn(BaseModel):
    entry: str
    note: str = ""


@router.post("/exclusions")
def exclusion_add(body: ExclusionIn):
    entry = suppression.normalize_entry(body.entry)
    if entry is None:
        raise HTTPException(400, "Saisissez une adresse (nom@domaine.ma) ou un domaine (domaine.ma).")
    with get_session() as s:
        added = suppression.add(s, entry, MANUAL_REASON + (f" – {body.note.strip()}" if body.note.strip() else ""))
        affected = 0
        for c in s.scalars(select(Contact).where(Contact.global_status == "active")):
            if suppression.is_suppressed(c.email, {entry}):
                cs.set_do_not_contact(s, c)
                affected += 1
        s.commit()
    return {"entry": entry, "added": added, "affected": affected}


@router.delete("/exclusions/{sid:int}")
def exclusion_delete(sid: int):
    require_admin_or_owner(None, "Retirer une adresse de la liste d'exclusion est réservé à l'administrateur.")
    with get_session() as s:
        row = s.get(Suppression, sid)
        if row is None or not row.reason.startswith(MANUAL_REASON):
            raise HTTPException(403, "Cette entrée ne peut pas être retirée (STOP ou effacement).")
        s.delete(row)
        s.commit()
    return {"ok": True}

"""API V2.3 : entreprises (liste, fiche, type, fusion) et ajout d'un contact à une campagne."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from sqlalchemy import func, select

from app import campaigns_service as camp_svc
from app import companies_service as co
from app import contacts_service as cs
from app.db import get_session
from app.models import Campaign, Company, Contact, Enrollment, Message, Sequence
from app.web.api_common import contact_ref, iso, not_found, require_admin_or_owner

router = APIRouter(prefix="/api")
EDITABLE = ("domain", "website", "phone", "sector", "notes")


def _summary(c: Company, n: int) -> dict:
    return {"id": c.id, "name": c.name, "kind": c.kind, "domain": c.domain, "sector": c.sector,
            "website": c.website, "phone": c.phone, "people": n,
            "logo": f"/api/companies/{c.id}/logo?v={c.logo}" if c.logo else None}


def _error(exc: co.CompanyError) -> HTTPException:
    detail = {"errors": {exc.field: str(exc)}}
    if exc.existing_id:
        detail["existing_id"] = exc.existing_id
    return HTTPException(409 if exc.existing_id else 422, detail)


@router.get("/companies")
def companies(q: str = "", kind: str = ""):
    with get_session() as s:
        n = co.counts(s)
        stmt = select(Company).order_by(func.lower(Company.name))
        if kind:
            stmt = stmt.where(Company.kind == kind)
        # Chaque mot doit se trouver dans l'entreprise OU chez une de ses personnes (nom, poste, email) :
        # « sanlam gestionnaire » trouve Sanlam.
        for word in q.split()[:6]:
            like = f"%{word}%"
            stmt = stmt.where(Company.name.ilike(like) | Company.domain.ilike(like) | Company.sector.ilike(like)
                              | Company.id.in_(select(Contact.company_id).where(
                                  Contact.first_name.ilike(like) | Contact.last_name.ilike(like)
                                  | Contact.job_title.ilike(like) | Contact.email.ilike(like))))
        # V2.7 : assureurs d'abord, puis clients, prospects, partenaires (ordre voulu par Omar)
        rank = {"insurer": 0, "client": 1, "prospect": 2, "partner": 3}
        items = sorted((_summary(c, n.get(c.id, 0)) for c in s.scalars(stmt)), key=lambda c: (rank[c["kind"]], c["name"].lower()))
        kinds = dict(s.execute(select(Company.kind, func.count(Company.id)).group_by(Company.kind)).all())
        return {"items": items, "kinds": [{"value": k, "label": v, "count": kinds.get(k, 0)}
                                          for k, v in co.KIND_LABELS.items()],
                "total": sum(kinds.values())}


@router.post("/companies")
def company_create(body: dict):
    name = " ".join(str(body.get("name") or "").split())
    if not name:
        raise HTTPException(422, {"errors": {"name": "Le nom est obligatoire."}})
    with get_session() as s:
        if (other := co.find(s, name)) is not None:
            raise HTTPException(409, {"errors": {"name": f"« {other.name} » existe déjà."}, "existing_id": other.id})
        kind = body.get("kind") or "prospect"
        if kind not in co.KIND_LABELS:
            raise HTTPException(422, {"errors": {"kind": "Type inconnu."}})
        comp, _ = co.get_or_create(s, name, kind)
        for f in EDITABLE:
            if body.get(f):
                setattr(comp, f, str(body[f]).strip())
        s.commit()
        return {"id": comp.id}


@router.get("/companies/{cid:int}")
def company_detail(cid: int):
    with get_session() as s:
        comp = s.get(Company, cid)
        if comp is None:
            raise not_found("Entreprise")
        people = co.people(s, comp)
        ids = [p.id for p in people]
        running = dict(s.execute(
            select(Enrollment.contact_id, Campaign.name).join(Campaign, Campaign.id == Enrollment.campaign_id)
            .where(Enrollment.contact_id.in_(ids), Enrollment.status.in_(cs.ACTIVE_ENROLLMENT))).all()) if ids else {}
        by_id = {p.id: p for p in people}
        msgs = s.scalars(select(Message).where(Message.contact_id.in_(ids))
                         .order_by(func.coalesce(Message.sent_at, Message.received_at).desc()).limit(25)) if ids else []
        return {
            **_summary(comp, len(people)), "notes": comp.notes, "created_at": iso(comp.created_at),
            "people": [{**contact_ref(p), "job_title": p.job_title, "status": p.global_status, "kind": p.kind,
                        "department": p.department, "seniority": p.seniority,
                        "campaign": running.get(p.id)} for p in people],
            "activity": [{"id": m.id, "direction": m.direction, "kind": m.kind, "subject": m.subject, "attachments": m.attachments or [],
                          "ts": iso(m.sent_at or m.received_at), "contact": contact_ref(by_id[m.contact_id])}
                         for m in msgs if (m.sent_at or m.received_at)],
        }


@router.put("/companies/{cid:int}")
def company_update(cid: int, body: dict):
    with get_session() as s:
        comp = s.get(Company, cid)
        if comp is None:
            raise not_found("Entreprise")
        stopped = 0
        try:
            if "name" in body and " ".join(str(body["name"]).split()) != comp.name:
                co.rename(s, comp, str(body["name"]))
            if body.get("kind") and body["kind"] != comp.kind:
                stopped = co.set_kind(s, comp, body["kind"])
        except co.CompanyError as exc:
            s.rollback()
            raise _error(exc) from None
        for f in EDITABLE:
            if f in body:
                v = str(body[f] or "").replace("\r\n", "\n").strip()
                setattr(comp, f, v if f == "notes" else (v or None))
        s.commit()
        return {"stopped": stopped}


@router.post("/companies/{cid:int}/merge")
def company_merge(cid: int, body: dict):
    require_admin_or_owner(None, "Fusionner des entreprises est réservé à l'administrateur.")
    with get_session() as s:
        src, dst = s.get(Company, cid), s.get(Company, int(body.get("into_id") or 0))
        if src is None or dst is None:
            raise not_found("Entreprise")
        try:
            moved = co.merge(s, src, dst)
        except co.CompanyError as exc:
            raise _error(exc) from None
        s.commit()
        return {"moved": moved, "id": dst.id}


@router.delete("/companies/{cid:int}")
def company_delete(cid: int):
    require_admin_or_owner(None, "Supprimer une entreprise est réservé à l'administrateur.")
    with get_session() as s:
        comp = s.get(Company, cid)
        if comp is None:
            raise not_found("Entreprise")
        if co.people(s, comp):
            raise HTTPException(409, "Cette entreprise a encore des personnes : rattachez-les ailleurs ou fusionnez la fiche.")
        s.delete(comp)
        s.commit()
        return {"ok": True}


# ------------------------------------------------- un contact dans une campagne

@router.get("/campaigns-open")
def open_campaigns():
    """Campagnes où l'on peut ajouter un contact à la main (en cours ou en pause)."""
    with get_session() as s:
        return [{"id": c.id, "name": c.name, "status": c.status, "category": cat or "prospection"}
                for c, cat in s.execute(select(Campaign, Sequence.category).join(Sequence, Sequence.id == Campaign.sequence_id)
                                        .where(Campaign.status.in_(("active", "paused")))
                                        .order_by(Campaign.created_at.desc()))]


@router.post("/campaigns/{camp_id:int}/enroll")
def enroll(camp_id: int, body: dict):
    with get_session() as s:
        camp, contact = s.get(Campaign, camp_id), s.get(Contact, int(body.get("contact_id") or 0))
        if camp is None or contact is None:
            raise not_found("Campagne ou contact")
        try:
            enr = camp_svc.enroll_one(s, camp, contact, bool(body.get("overlap")))
        except camp_svc.EnrollRefused as exc:
            s.rollback()
            raise HTTPException(409, {"message": str(exc), "problems": exc.problems, "overlap": exc.overlap}) from None
        s.commit()
        return {"id": enr.id, "variant": enr.variant_label, "paused": camp.status == "paused"}

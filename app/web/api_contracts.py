"""API des contrats et échéances (voir app/contracts.py)."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app import contracts, quotes
from app.db import get_session
from app.models import Contract, QuoteCase
from app.web.api_common import not_found, require_admin_or_owner

router = APIRouter(prefix="/api")


def _err(exc: contracts.ContractError | quotes.QuoteError) -> HTTPException:
    return HTTPException(422, {"errors": exc.errors})


def _contract(s, cid: int) -> Contract:
    c = s.get(Contract, cid)
    if c is None:
        raise not_found("Contrat")
    return c


@router.get("/contracts")
def list_contracts(f: str = "upcoming", q: str = "", branch: str = "", owner: str = "", company_id: int | None = None):
    if f not in contracts.FILTERS:
        f = "upcoming"
    with get_session() as s:
        names = contracts._names(s)
        day = contracts.today()
        return {"filter": f, "filters": [{"key": k, "label": v} for k, v in contracts.FILTERS.items()],
                "summary": contracts.summary(s, day),
                "items": [contracts.to_json(s, c, names, day)
                          for c in contracts.listing(s, f, q, branch, owner, company_id, day)],
                "branches": [b["name"] for b in quotes.branches()],
                "notice_days": contracts.default_notice(s)}


@router.post("/contracts")
def create_contract(body: dict):
    with get_session() as s:
        try:
            c = contracts.create(s, body)
        except contracts.ContractError as exc:
            s.rollback()
            raise _err(exc) from None
        s.commit()
        return contracts.to_json(s, c)


@router.get("/contracts/{cid:int}")
def get_contract(cid: int):
    with get_session() as s:
        return contracts.to_json(s, _contract(s, cid))


@router.patch("/contracts/{cid:int}")
def update_contract(cid: int, body: dict):
    with get_session() as s:
        c = _contract(s, cid)
        try:
            contracts.update(s, c, body)
        except contracts.ContractError as exc:
            s.rollback()
            raise _err(exc) from None
        s.commit()
        return contracts.to_json(s, c)


@router.delete("/contracts/{cid:int}")
def delete_contract(cid: int):
    with get_session() as s:
        c = _contract(s, cid)
        require_admin_or_owner(c.owner_id, "Seul le gestionnaire du contrat ou l'administrateur peut le supprimer.")
        s.delete(c)  # ses rappels partent avec lui (ON DELETE CASCADE)
        s.commit()
        return {"ok": True}


@router.post("/contracts/{cid:int}/renew")
def renew(cid: int, body: dict | None = None):
    """Renouvelé à l'identique (même compagnie) : période suivante, prime / taux modifiables."""
    with get_session() as s:
        c = _contract(s, cid)
        try:
            contracts.renew_same(s, c, body or {})
        except contracts.ContractError as exc:
            s.rollback()
            raise _err(exc) from None
        s.commit()
        return contracts.to_json(s, c)


@router.post("/contracts/{cid:int}/start-renewal")
def start_renewal(cid: int):
    with get_session() as s:
        c = _contract(s, cid)
        try:
            case = contracts.start_renewal(s, c)
        except (contracts.ContractError, quotes.QuoteError) as exc:
            s.rollback()
            raise _err(exc) from None
        s.commit()
        return {"quote_id": case.id, "contract": contracts.to_json(s, c)}


@router.post("/contracts/{cid:int}/end")
def end_contract(cid: int, body: dict):
    with get_session() as s:
        c = _contract(s, cid)
        try:
            contracts.end(s, c, str(body.get("reason") or ""))
        except contracts.ContractError as exc:
            raise _err(exc) from None
        s.commit()
        return contracts.to_json(s, c)


def _case(s, qid: int) -> QuoteCase:
    case = s.get(QuoteCase, qid)
    if case is None:
        raise not_found("Dossier")
    return case


@router.get("/quotes/{qid:int}/contract-draft")
def contract_draft(qid: int):
    """Pré-remplissage de « Dossier gagné » : compagnie retenue, prime, dates, préavis."""
    with get_session() as s:
        return contracts.case_draft(s, _case(s, qid))


@router.post("/quotes/{qid:int}/win")
def win(qid: int, body: dict):
    """Dossier gagné, avec (ou sans) les contrats à enregistrer."""
    with get_session() as s:
        case = _case(s, qid)
        try:
            made = contracts.from_case(s, case, body.get("items") or [])
            if case.stage != "won":
                quotes.set_stage(s, case, "won")
        except (contracts.ContractError, quotes.QuoteError) as exc:
            s.rollback()
            raise _err(exc) from None
        s.commit()
        return {"contracts": [contracts.to_json(s, c) for c in made], "quote": quotes.detail_json(s, case)}

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


def _filters(f: str, q: str, branch: str, owner: str, company_id: int | None, contact_id: int | None,
             policy: str, insurer: str, end_from: str, end_to: str, sort: str) -> dict:
    return {"flt": f if f in contracts.FILTERS else "active", "q": q, "branch": branch, "owner": owner,
            "company_id": company_id, "contact_id": contact_id, "policy": policy, "insurer": insurer,
            "end_from": contracts._date(end_from, "end_from"), "end_to": contracts._date(end_to, "end_to"),
            "sort": sort if sort in contracts.SORTS else "deadline"}


@router.get("/contracts")
def list_contracts(f: str = "active", q: str = "", branch: str = "", owner: str = "", company_id: int | None = None,
                   contact_id: int | None = None, policy: str = "", insurer: str = "", end_from: str = "",
                   end_to: str = "", sort: str = "deadline", limit: int = 500):
    with get_session() as s:
        names = contracts._names(s)
        day = contracts.today()
        try:
            flt = _filters(f, q, branch, owner, company_id, contact_id, policy, insurer, end_from, end_to, sort)
        except contracts.ContractError as exc:
            raise _err(exc) from None
        rows = contracts.listing(s, now_day=day, **flt)
        return {"filter": flt["flt"], "filters": [{"key": k, "label": v} for k, v in contracts.FILTERS.items()],
                "sorts": [{"key": k, "label": v} for k, v in contracts.SORTS.items()],
                "summary": contracts.summary(s, day), "totals": contracts.totals(rows),
                "items": [contracts.to_json(s, c, names, day) for c in rows[:max(1, min(limit, 2000))]],
                "branches": list(contracts.branch_settings(s)["items"]),
                "notice_days": contracts.default_notice(s)}


@router.get("/contracts/export.xlsx")
def export_contracts(f: str = "active", q: str = "", branch: str = "", owner: str = "", company_id: int | None = None,
                     contact_id: int | None = None, policy: str = "", insurer: str = "", end_from: str = "",
                     end_to: str = "", sort: str = "deadline"):
    """La liste affichée (mêmes filtres), en Excel."""
    from io import BytesIO

    from fastapi.responses import StreamingResponse
    from openpyxl import Workbook
    from openpyxl.styles import Font
    with get_session() as s:
        names = contracts._names(s)
        day = contracts.today()
        rows = contracts.listing(s, now_day=day, **_filters(f, q, branch, owner, company_id, contact_id, policy,
                                                             insurer, end_from, end_to, sort))
        wb = Workbook()
        ws = wb.active
        ws.title = "Contrats"
        head = ["Client", "Branche", "Compagnie", "N° de police", "Base de calcul", "Montant de la base", "Taux",
                "Prime nette", "Accessoires", "Taxes", "Prime TTC", "Commission (%)", "Commission", "Date d'effet",
                "Échéance", "Préavis (jours)", "Date limite de préavis", "Statut", "Gestionnaire"]
        ws.append(head)
        for cell in ws[1]:
            cell.font = Font(bold=True)
        for c in rows:
            j = contracts.to_json(s, c, names, day)
            ws.append([j["client_name"], j["branch"], j["insurer_name"], j["policy_number"], j["base_label"], j["base_amount"],
                       j["rate"], j["premium"], j["accessories"], j["taxes"], j["ttc"], j["commission_rate"], j["commission"],
                       c.start_date, c.end_date, j["notice_days"], contracts.deadline(c),
                       j["status_label"] + (f" ({j['end_reason']})" if j["end_reason"] else ""), (j["owner"] or {}).get("name", "")])
        for col, w in zip("ABCDEFGHIJKLMNOPQRS", (28, 22, 24, 16, 18, 16, 10, 13, 12, 11, 13, 14, 12, 12, 12, 10, 14, 22, 18)):
            ws.column_dimensions[col].width = w
        for row in ws.iter_rows(min_row=2):
            for cell in row[13:17]:
                if cell.value is not None and not isinstance(cell.value, int):
                    cell.number_format = "DD/MM/YYYY"
        ws.freeze_panes = "A2"
        buf = BytesIO()
        wb.save(buf)
        buf.seek(0)
        return StreamingResponse(buf, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                                 headers={"Content-Disposition": f'attachment; filename="contrats-{day.isoformat()}.xlsx"'})


@router.get("/contracts/branches")
def get_branch_settings():
    """Par branche : base de calcul de la prime, taxes, commission par défaut (réglage du cabinet)."""
    with get_session() as s:
        return contracts.branch_settings(s)


@router.put("/contracts/branches")
def put_branch_settings(body: dict):
    from app.current import is_admin
    if not is_admin():  # poste unique : toujours vrai ; serveur : l'administrateur seulement
        raise HTTPException(403, "Seul l'administrateur peut changer les taxes et commissions par défaut.")
    with get_session() as s:
        try:
            out = contracts.save_branch_settings(s, body.get("items") or {})
        except contracts.ContractError as exc:
            s.rollback()
            raise _err(exc) from None
        s.commit()
        return out


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

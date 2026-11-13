"""V3.10 : portefeuille clients (import DIAMM, tableau de bord, vente croisée)."""
from __future__ import annotations

import tempfile
from datetime import date
from pathlib import Path

from fastapi import APIRouter, HTTPException, UploadFile
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from app import portfolio as pf
from app.current import is_admin
from app.db import get_session

router = APIRouter(prefix="/api/portfolio")


@router.post("/import")
async def import_portfolio(file: UploadFile):
    """L'export DIAMM tel quel. Réservé à l'administrateur : il met à jour le portefeuille de toute l'équipe."""
    if not is_admin():
        raise HTTPException(403, "Réservé à l'administrateur.")
    ext = Path(file.filename or "").suffix.lower()
    if ext not in (".xls", ".xlsx", ".xlsm", ".csv"):
        raise HTTPException(400, "Format non pris en charge : choisissez l'export DIAMM en .xls, .xlsx ou .csv.")
    data = await file.read(pf.MAX_FILE + 1)
    if len(data) > pf.MAX_FILE:
        raise HTTPException(400, "Fichier trop volumineux (30 Mo maximum).")

    def run():
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / f"portefeuille{ext}"
            path.write_bytes(data)
            with get_session() as s:
                try:
                    rep = pf.import_file(s, path)
                except pf.PortfolioError as exc:
                    s.rollback()
                    raise HTTPException(400, str(exc)) from None
                s.commit()
                return rep.as_dict()
    return await run_in_threadpool(run)


@router.get("/summary")
async def portfolio_summary():
    def run():
        with get_session() as s:
            return pf.summary(s)
    return await run_in_threadpool(run)


@router.get("/clients")
async def portfolio_clients(q: str = "", segment: str = "", has: str = "", lacks: str = "", rule: str = "", reach: str = "",
                            called: str = "", calls_first: bool = False, offset: int = 0, limit: int = 100):
    def run():
        with get_session() as s:
            return pf.clients(s, offset=max(0, offset), limit=max(1, min(limit, 500)), q=q, segment=segment, has=has,
                              lacks=lacks, rule=rule, reach=reach, called=called, calls_first=calls_first)
    return await run_in_threadpool(run)


@router.get("/clients/{client_id:int}")
def portfolio_client(client_id: int):
    with get_session() as s:
        d = pf.detail(s, client_id)
        if d is None:
            raise HTTPException(404, "Client introuvable.")
        return d


class ListIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    q: str = ""
    segment: str = ""
    has: str = ""
    lacks: str = ""
    rule: str = ""
    ids: list[int] | None = None


@router.post("/list")
def portfolio_list(body: ListIn):
    """« Créer la liste » : les clients sélectionnés (ou le filtre en cours) qui ont un email, pour une campagne."""
    from app.lists_service import ListError
    with get_session() as s:
        views = pf.search(s, q=body.q, segment=body.segment, has=body.has, lacks=body.lacks, rule=body.rule, ids=body.ids)
        if not any(v.c.contact_id for v in views):
            raise HTTPException(422, "Aucun de ces clients n'a d'email : utilisez plutôt la liste d'appels.")
        try:
            cl, added, without = pf.make_list(s, body.name, views)
        except ListError as exc:
            raise HTTPException(422, str(exc)) from None
        s.commit()
        return {"list_id": cl.id, "added": added, "without_email": without}


def _client(s, client_id: int):
    from app.models import PortfolioClient
    c = s.get(PortfolioClient, client_id)
    if c is None or c.org_id != pf._org():
        raise HTTPException(404, "Client introuvable.")
    return c


class EmailIn(BaseModel):
    email: str | None = Field(default=None, max_length=254)


@router.put("/clients/{client_id:int}/email")
def portfolio_email(client_id: int, body: EmailIn):
    """Email noté sur la fiche : le client devient joignable par les campagnes (contact « client »)."""
    with get_session() as s:
        c = _client(s, client_id)
        try:
            pf.set_email(s, c, body.email)
        except pf.PortfolioError as exc:
            raise HTTPException(422, str(exc)) from None
        s.commit()
        return pf.detail(s, client_id)


class CallIn(BaseModel):
    outcome: str = Field(pattern="^(interested|callback|not_interested|no_answer|wrong_number|done)$")
    note: str = Field(default="", max_length=2000)
    callback_on: date | None = None
    rule: str | None = Field(default=None, max_length=60)
    email: str | None = Field(default=None, max_length=254)


@router.post("/clients/{client_id:int}/calls")
def portfolio_call(client_id: int, body: CallIn):
    """Résultat d'un appel (liste d'appels) ; « À rappeler » demande une date, qui arrive dans la cloche."""
    with get_session() as s:
        c = _client(s, client_id)
        try:
            pf.log_call(s, c, body.outcome, body.note, body.callback_on, body.rule, body.email)
        except pf.PortfolioError as exc:
            raise HTTPException(422, str(exc)) from None
        s.commit()
        return pf.detail(s, client_id)


@router.get("/callbacks")
def portfolio_callbacks(days: int = 0):
    """Rappels prévus jusqu'à aujourd'hui + `days` jours (toute l'équipe)."""
    from datetime import timedelta

    from app.timeutil import to_local, utcnow
    with get_session() as s:
        return {"items": pf.callbacks(s, to_local(utcnow()).date() + timedelta(days=max(0, min(days, 60))))}


# ---- V3.12 : saisie dans l'appli (nouveaux clients et contrats, relais de DIAMM). Toute l'équipe.

@router.get("/options")
def portfolio_options():
    with get_session() as s:
        return pf.options(s)


class PhoneIn(BaseModel):
    number: str = Field(max_length=40)
    label: str = Field(default="", max_length=60)


class ClientIn(BaseModel):
    name: str | None = Field(default=None, max_length=255)
    segment: str | None = Field(default=None, pattern="^(particulier|pro)$")
    email: str | None = Field(default=None, max_length=254)
    phones: list[PhoneIn] | None = None
    note: str | None = Field(default=None, max_length=2000)


def _client_data(body: ClientIn) -> dict:
    data = body.model_dump(exclude_unset=True)
    if "phones" in data and data["phones"] is not None:
        data["phones"] = [p for p in data["phones"]]
    return data


def _refuse(exc: pf.PortfolioError):
    if isinstance(exc, pf.DuplicateClient):
        raise HTTPException(409, {"message": str(exc), "existing_id": exc.existing_id}) from None
    raise HTTPException(422, str(exc)) from None


@router.post("/clients")
def portfolio_create_client(body: ClientIn):
    with get_session() as s:
        try:
            c = pf.create_client(s, _client_data(body))
        except pf.PortfolioError as exc:
            _refuse(exc)
        s.commit()
        return pf.detail(s, c.id)


@router.put("/clients/{client_id:int}")
def portfolio_update_client(client_id: int, body: ClientIn):
    with get_session() as s:
        c = _client(s, client_id)
        try:
            pf.update_client(s, c, _client_data(body))
        except pf.PortfolioError as exc:
            _refuse(exc)
        s.commit()
        return pf.detail(s, client_id)


class ContractIn(BaseModel):
    insurer: str | None = Field(default=None, max_length=120)
    policy: str | None = Field(default=None, max_length=80)
    branch: str | None = Field(default=None, max_length=120)
    start_date: date | None = None
    due_date: date | None = None
    premium: float | None = Field(default=None, ge=0)
    fleet: bool | None = None
    fixed_term: bool | None = None
    note: str | None = Field(default=None, max_length=2000)
    cancelled: bool | None = None
    cancelled_on: date | None = None
    attachment_ids: list[int] | None = None  # V3.13 : contrat scanné…
    subscribed_on: date | None = None
    last_claim_on: date | None = None
    aperiteur_no: str | None = Field(default=None, max_length=80)
    coinsurance: bool | None = None


def _contract(s, contract_id: int):
    from app.models import PortfolioContract
    ct = s.get(PortfolioContract, contract_id)
    if ct is None or ct.org_id != pf._org():
        raise HTTPException(404, "Contrat introuvable.")
    return ct


@router.post("/clients/{client_id:int}/contracts")
def portfolio_add_contract(client_id: int, body: ContractIn):
    with get_session() as s:
        c = _client(s, client_id)
        try:
            pf.add_contract(s, c, body.model_dump(exclude_unset=True))
        except pf.PortfolioError as exc:
            _refuse(exc)
        s.commit()
        return pf.detail(s, client_id)


@router.put("/contracts/{contract_id:int}")
def portfolio_update_contract(contract_id: int, body: ContractIn):
    with get_session() as s:
        ct = _contract(s, contract_id)
        try:
            pf.update_contract(s, ct, body.model_dump(exclude_unset=True))
        except pf.PortfolioError as exc:
            _refuse(exc)
        s.commit()
        return pf.detail(s, ct.client_id)


@router.delete("/contracts/{contract_id:int}")
def portfolio_delete_contract(contract_id: int):
    with get_session() as s:
        ct = _contract(s, contract_id)
        cid = ct.client_id
        try:
            pf.delete_contract(s, ct)
        except pf.PortfolioError as exc:
            _refuse(exc)
        s.commit()
        return pf.detail(s, cid)


# ---- V3.13 : avenants (rattachés à un contrat) et leurs pièces jointes

class AmendmentIn(BaseModel):
    effective_on: date | None = None
    kind: str | None = Field(default=None, max_length=60)
    number: str | None = Field(default=None, max_length=60)
    description: str | None = Field(default=None, max_length=4000)
    premium_delta: float | None = None  # + ou - (MAD)
    attachment_ids: list[int] | None = None


def _amendment(s, amendment_id: int):
    from app.models import PortfolioAmendment
    a = s.get(PortfolioAmendment, amendment_id)
    if a is None or a.org_id != pf._org():
        raise HTTPException(404, "Avenant introuvable.")
    return a


@router.post("/contracts/{contract_id:int}/amendments")
def portfolio_add_amendment(contract_id: int, body: AmendmentIn):
    with get_session() as s:
        ct = _contract(s, contract_id)
        try:
            pf.add_amendment(s, ct, body.model_dump(exclude_unset=True))
        except pf.PortfolioError as exc:
            _refuse(exc)
        s.commit()
        return pf.detail(s, ct.client_id)


@router.put("/amendments/{amendment_id:int}")
def portfolio_update_amendment(amendment_id: int, body: AmendmentIn):
    with get_session() as s:
        a = _amendment(s, amendment_id)
        try:
            pf.update_amendment(s, a, body.model_dump(exclude_unset=True))
        except pf.PortfolioError as exc:
            _refuse(exc)
        cid = _contract(s, a.contract_id).client_id
        s.commit()
        return pf.detail(s, cid)


@router.delete("/amendments/{amendment_id:int}")
def portfolio_delete_amendment(amendment_id: int):
    with get_session() as s:
        a = _amendment(s, amendment_id)
        cid = _contract(s, a.contract_id).client_id
        s.delete(a)
        s.commit()
        return pf.detail(s, cid)


@router.get("/amendment-kinds")
def portfolio_amendment_kinds():
    return {"items": list(pf.AMENDMENT_KINDS)}

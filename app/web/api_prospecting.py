"""V3.7 : « Trouver des prospects » (looot), réservé à l'administrateur (voir app/prospecting.py)."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from starlette.concurrency import run_in_threadpool

from app import prospecting as pr
from app.db import get_session
from app.models import ProspectSearch
from app.web.api_common import not_found

router = APIRouter(prefix="/api/prospecting")


def _admin() -> None:
    from app.current import is_admin
    if not is_admin():
        raise HTTPException(403, "La recherche de prospects est réservée à l'administrateur.")


class KeyIn(BaseModel):
    key: str = Field(min_length=10, max_length=400)


class CriteriaIn(BaseModel):
    functions: list[str] = []
    sectors: list[str] = []
    details: list[str] = []  # industries précises : « SRV.banque »…
    cities: list[str] = []
    sizes: list[str] = []
    wanted: int = 50


class StartIn(BaseModel):
    wanted: int | None = None


def _fail(exc: Exception):
    if isinstance(exc, pr.NoCredit):
        return HTTPException(402, str(exc))
    if isinstance(exc, pr.LoootError):
        return HTTPException(424 if exc.code != "no_key" else 409, str(exc))
    return HTTPException(502, f"looot ne répond pas : {exc}")


@router.get("")
def index():
    _admin()
    with get_session() as s:
        pr.purge_old_previews(s)
        s.commit()
        rows = s.scalars(select(ProspectSearch).where(ProspectSearch.status != "preview")
                         .order_by(ProspectSearch.id.desc()).limit(30)).all()
        return {"configured": bool(pr.get_key()), "options": pr.options(), "items": [pr.to_json(r) for r in rows]}


@router.get("/balance")
async def balance():
    _admin()
    try:
        return {"balance": await run_in_threadpool(lambda: pr.client().balance())}
    except Exception as exc:  # noqa: BLE001
        raise _fail(exc) from None


@router.put("/key")
async def save_key(body: KeyIn):
    """Vérifie la clé auprès de looot (lecture du solde, gratuite) avant de la ranger dans le coffre."""
    _admin()
    key = body.key.strip()
    try:
        bal = await run_in_threadpool(lambda: pr.Client(key, transport=pr._TRANSPORT).balance())
    except pr.LoootError as exc:
        raise HTTPException(422, "Clé refusée par looot : vérifiez-la." if exc.status == 401 else str(exc)) from None
    except Exception as exc:  # noqa: BLE001
        raise _fail(exc) from None
    pr.set_key(key)
    return {"configured": True, "balance": bal}


@router.delete("/key")
def remove_key():
    _admin()
    pr.delete_key()
    return {"configured": False}


@router.post("/preview")
async def preview(body: CriteriaIn):
    """Aperçu (une page, ≈ 0,04 $) : nombre de profils, échantillon, coût estimé pour le nombre voulu."""
    _admin()

    def go():
        with get_session() as s:
            ps = pr.preview(s, body.model_dump())
            s.commit()
            return pr.to_json(ps, sample=True)
    try:
        return await run_in_threadpool(go)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    except Exception as exc:  # noqa: BLE001
        raise _fail(exc) from None


@router.get("/{sid:int}")
def detail(sid: int):
    _admin()
    with get_session() as s:
        ps = s.get(ProspectSearch, sid)
        if ps is None:
            raise not_found("Recherche")
        return pr.to_json(ps, sample=ps.status == "preview")


@router.post("/{sid:int}/start")
def start(sid: int, body: StartIn):
    _admin()
    with get_session() as s:
        ps = s.get(ProspectSearch, sid)
        if ps is None:
            raise not_found("Recherche")
        try:
            pr.start(ps, body.wanted)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from None
        s.commit()
        return pr.to_json(ps)


@router.post("/{sid:int}/stop")
def stop(sid: int):
    _admin()
    with get_session() as s:
        ps = s.get(ProspectSearch, sid)
        if ps is None:
            raise not_found("Recherche")
        pr.stop(ps, "Arrêtée par vous")
        s.commit()
        return pr.to_json(ps)

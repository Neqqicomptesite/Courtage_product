"""V3.6 : listes de contacts (voir app/lists_service.py)."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app import lists_service as ls
from app.db import get_session
from app.models import Campaign, ContactList
from app.web.api_common import not_found

router = APIRouter(prefix="/api")


def _list(s, lid: int, edit: bool = False) -> ContactList:
    cl = s.get(ContactList, lid)
    if cl is None:
        raise not_found("Liste")
    if edit and not ls.can_edit(cl):
        raise HTTPException(403, "Cette liste appartient à un collègue : vous pouvez l'utiliser, pas la modifier.")
    return cl


class ListIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    contact_ids: list[int] = []


class MembersIn(BaseModel):
    contact_ids: list[int] = Field(min_length=1, max_length=20000)


class RenameIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)


class ShareIn(BaseModel):
    shared: bool


@router.get("/lists")
def lists_index():
    with get_session() as s:
        return {"items": ls.listing(s)}


@router.post("/lists")
def list_create(body: ListIn):
    with get_session() as s:
        try:
            cl = ls.create(s, body.name, body.contact_ids)
        except ls.ListError as exc:
            raise HTTPException(422, str(exc)) from None
        s.commit()
        return ls.to_json(s, cl)


@router.put("/lists/{lid:int}")
def list_rename(lid: int, body: RenameIn):
    with get_session() as s:
        cl = _list(s, lid, edit=True)
        try:
            ls.rename(cl, body.name)
        except ls.ListError as exc:
            raise HTTPException(422, str(exc)) from None
        s.commit()
        return ls.to_json(s, cl)


@router.delete("/lists/{lid:int}")
def list_delete(lid: int):
    """Supprime la liste, jamais les contacts."""
    with get_session() as s:
        s.delete(_list(s, lid, edit=True))
        s.commit()
        return {"ok": True}


@router.post("/lists/{lid:int}/members")
def list_add(lid: int, body: MembersIn):
    with get_session() as s:
        cl = _list(s, lid, edit=True)
        n = ls.add(s, cl, body.contact_ids)
        s.commit()
        return {"added": n, **ls.to_json(s, cl)}


@router.post("/lists/{lid:int}/members/remove")
def list_remove(lid: int, body: MembersIn):
    with get_session() as s:
        cl = _list(s, lid, edit=True)
        n = ls.remove(s, cl, body.contact_ids)
        s.commit()
        return {"removed": n, **ls.to_json(s, cl)}


@router.post("/lists/{lid:int}/share")
def list_share(lid: int, body: ShareIn):
    """Partager avec l'équipe (tous la voient et s'en servent ; seuls l'auteur et l'administrateur la modifient)."""
    with get_session() as s:
        cl = _list(s, lid, edit=True)
        cl.shared = body.shared
        s.commit()
        return ls.to_json(s, cl)


@router.post("/campaigns/{cid:int}/no-reply-list")
def campaign_no_reply_list(cid: int):
    """Enregistre dans une nouvelle liste ceux qui sont allés au bout de la campagne sans répondre."""
    with get_session() as s:
        camp = s.get(Campaign, cid)
        if camp is None:
            raise not_found("Campagne")
        try:
            cl = ls.from_campaign_no_reply(s, camp)
        except ls.ListError as exc:
            raise HTTPException(409, str(exc)) from None
        s.commit()
        return ls.to_json(s, cl)

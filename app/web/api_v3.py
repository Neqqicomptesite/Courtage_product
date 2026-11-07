"""V3 : adresses de l'API qui remplacent les pages « classiques » encore utilisées par la V2."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from starlette.concurrency import run_in_threadpool

from app import export
from app.db import get_session
from app.models import Campaign
from app.timeutil import to_local, utcnow

router = APIRouter(prefix="/api")


@router.get("/export")
async def export_xlsx(campaign_id: int | None = None):
    """Export Excel (toutes mes campagnes, ou une seule). Sur le serveur, ne contient que les
    campagnes de l'employé connecté (filtre global de app.scope)."""
    def build():
        with get_session() as s:
            name = "toutes-campagnes"
            if campaign_id:
                camp = s.get(Campaign, campaign_id)
                if camp is None:
                    raise HTTPException(404, "Campagne introuvable.")
                name = "".join(ch if ch.isalnum() else "-" for ch in camp.name).strip("-").lower()[:40] or "campagne"
            return export.build(s, campaign_id), name
    data, name = await run_in_threadpool(build)
    filename = f"oddo-sequences_{name}_{to_local(utcnow()):%Y-%m-%d}.xlsx"
    return Response(data, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f'attachment; filename="{filename}"'})

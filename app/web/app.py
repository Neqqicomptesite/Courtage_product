"""Création de l'application FastAPI."""
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from app import HOST, PORT, scheduler, starter_data, vocab
from app.db import get_session, init_engine
from app.logging_setup import setup_logging
from app.paths import STATIC_DIR, ensure_dirs, is_server_mode
from app.web import api_users
from app.web.server_auth import SupabaseAuthMiddleware
from app import auth
from app.seed import run_seed
from app.web import (api, api_campaigns, api_companies, api_contacts, api_mailbox, api_misc, api_sequences, api_v28, routes_campaigns, routes_contacts, routes_pages, routes_replies, routes_sequences,
                     routes_settings)
from app.web.security import LocalOnlyMiddleware


def create_app(testing: bool = False) -> FastAPI:
    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        ensure_dirs()
        setup_logging()
        init_engine()
        if is_server_mode():
            auth.ensure_admin_from_env()  # V3 : premier administrateur (ODDO_ADMIN_EMAIL)
        with get_session() as s, s.begin():
            run_seed(s)
            vocab.load_custom(s)  # V2.9 : fonctions et secteurs ajoutés par Omar
            if not testing:
                starter_data.apply_at_startup(s)  # V2.12 : compagnies d'assurance, logos et contacts de départ
        if not testing:
            scheduler.start()  # moteur d'envoi, sauvegarde quotidienne
        yield
        scheduler.stop()

    app = FastAPI(title="ODDO Séquences", lifespan=lifespan, docs_url=None, redoc_url=None)
    allowed = {f"{HOST}:{PORT}", f"localhost:{PORT}"}
    if testing:
        allowed.add("testserver")  # nom d'hôte utilisé par le client de test FastAPI
    if is_server_mode():
        # V3 : serveur en ligne : l'adresse publique (ex. sequences.oddo.ma) et connexion obligatoire
        allowed |= {h.strip().lower() for h in os.environ.get("ODDO_PUBLIC_HOSTS", "").split(",") if h.strip()}
        app.add_middleware(SupabaseAuthMiddleware)
    app.add_middleware(LocalOnlyMiddleware, allowed_hosts=allowed)
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    app.include_router(api_users.router)
    for r in (api.router, api_companies.router, api_mailbox.router, api_contacts.router, api_sequences.router, api_campaigns.router, api_misc.router, api_v28.router):
        app.include_router(r)

    # Interface V2 (React compilée dans app/static/v2). Les sections pas encore migrées
    # restent servies par les pages « classiques » de la V1, à leurs adresses habituelles.
    spa_index = STATIC_DIR / "v2" / "index.html"

    @app.get("/", include_in_schema=False)
    def root():
        return RedirectResponse("/v2/" if spa_index.exists() else "/classique")

    @app.get("/v2", include_in_schema=False)
    @app.get("/v2/{path:path}", include_in_schema=False)
    def spa(path: str = ""):
        # Toutes les adresses /v2/... renvoient la même page : c'est React qui affiche la bonne section.
        if not spa_index.exists():
            return RedirectResponse("/classique")
        return FileResponse(spa_index, headers={"Cache-Control": "no-cache"})

    if is_server_mode():
        # V3 : sur le serveur, seules l'API (protégée par la connexion) et l'interface V2
        # sont servies. Les pages « classiques » de la V1 ne vérifient pas la connexion.
        @app.get("/classique", include_in_schema=False)
        def no_classic():
            return RedirectResponse("/v2/")
        return app
    app.include_router(routes_pages.router)
    app.include_router(routes_settings.router)
    app.include_router(routes_contacts.router)
    app.include_router(routes_sequences.router)
    app.include_router(routes_campaigns.router)
    app.include_router(routes_replies.router)
    return app

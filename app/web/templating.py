"""Moteur de gabarits Jinja2 partagé par toutes les pages."""
from fastapi.templating import Jinja2Templates

from app import APP_NAME
from app import settings_store
from app.db import get_session
from app.paths import TEMPLATES_DIR
from app.importer import slug
from app.timeutil import fmt_local, fmt_local_long

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
templates.env.filters["local"] = fmt_local
templates.env.globals["app_name"] = APP_NAME
templates.env.filters["local_long"] = fmt_local_long
templates.env.filters["slug"] = slug  # « À vérifier » -> « a_verifier » (classes CSS)


def base_context(request, **extra) -> dict:
    """Variables disponibles dans toutes les pages (bandeau mode test, menu...)."""
    from app.stats import unclassified_count  # import local : évite un import circulaire
    with get_session() as s:
        test_mode = settings_store.get(s, "test_mode")
        to_classify = unclassified_count(s)
    ctx = {"request": request, "test_mode": test_mode, "nav": request.url.path, "to_classify": to_classify}
    ctx.update(extra)
    return ctx

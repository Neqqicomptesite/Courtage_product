"""Pages Contacts : liste, import, fiche, liste d'exclusion."""
import json
import re
import secrets
from pathlib import Path
from urllib.parse import urlencode

from fastapi import APIRouter, HTTPException, Request, UploadFile
from fastapi.responses import RedirectResponse
from sqlalchemy import select

from app import contacts_service as cs
from app import importer, settings_store, suppression
from app.db import get_session
from app.models import Contact, Suppression
from app.paths import data_dir
from app.timeutil import fmt_local, utcnow
from app.web.templating import base_context, templates

router = APIRouter(prefix="/contacts")

MAX_UPLOAD = 10 * 1024 * 1024  # 10 Mo : largement assez pour quelques milliers de lignes
TOKEN_RE = re.compile(r"^[0-9a-f]{16}$")
MANUAL_REASON = "Ajout manuel"


def _imports_dir() -> Path:
    d = data_dir() / "imports"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _upload(token: str) -> tuple[Path, dict]:
    """Retrouve un fichier envoyé. Le jeton est vérifié par une expression régulière :
    sans ça, un jeton du type « ../../oddo.db » permettrait de lire n'importe quel fichier."""
    if not TOKEN_RE.match(token):
        raise HTTPException(404)
    meta_path = _imports_dir() / f"{token}.json"
    if not meta_path.exists():
        raise HTTPException(404, "Import expiré ou déjà terminé.")
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    return _imports_dir() / f"{token}{meta['ext']}", meta


def _discard(token: str) -> None:
    # Minimisation des données : le fichier source n'est pas conservé après l'import.
    for f in _imports_dir().glob(f"{token}.*"):
        f.unlink(missing_ok=True)


# ------------------------------------------------------------------------ liste

@router.get("")
def contacts_list(request: Request):
    f = cs.ContactFilters.from_query(request.query_params)
    with get_session() as s:
        contacts = list(s.scalars(cs.filtered_query(f)))
        ctx = base_context(request, contacts=contacts, f=f, options=cs.filter_options(s),
                           total=cs.count_all(s), status_labels=cs.STATUS_LABELS,
                           category=cs.reliability_category,
                           imported=request.query_params.get("imported"))
    return templates.TemplateResponse(request, "contacts_list.html", ctx)


# ------------------------------------------------------------------------ import

@router.get("/import")
def import_form(request: Request, error: str = ""):
    return templates.TemplateResponse(request, "import_upload.html", base_context(request, error=error))


@router.post("/import")
async def import_upload(request: Request, file: UploadFile):
    name = Path(file.filename or "").name
    ext = Path(name).suffix.lower()
    if ext not in (".xlsx", ".xlsm", ".csv"):
        return import_form(request, error="Format non pris en charge : choisissez un fichier .xlsx ou .csv.")
    data = await file.read(MAX_UPLOAD + 1)
    if len(data) > MAX_UPLOAD:
        return import_form(request, error="Fichier trop volumineux (10 Mo maximum).")
    token = secrets.token_hex(8)
    (_imports_dir() / f"{token}{ext}").write_bytes(data)
    (_imports_dir() / f"{token}.json").write_text(
        json.dumps({"filename": name, "ext": ext}, ensure_ascii=False), encoding="utf-8")
    try:
        importer.read_table(_imports_dir() / f"{token}{ext}")
    except Exception as exc:  # noqa: BLE001 – fichier corrompu, protégé par mot de passe…
        _discard(token)
        return import_form(request, error=f"Fichier illisible : {exc}")
    return RedirectResponse(f"/contacts/import/{token}", status_code=303)


def _field_choices() -> list[tuple[str, str]]:
    return [("ignore", "— Ignorer —")] + [(f"field:{f}", label) for f, label in importer.CONTACT_FIELDS]


@router.get("/import/{token}")
def import_mapping(request: Request, token: str, sheet: str | None = None):
    path, meta = _upload(token)
    table = importer.read_table(path, sheet)
    mapping = importer.auto_mapping(table.headers)
    columns = []
    for i, (h, m) in enumerate(zip(table.headers, mapping)):
        samples = [r[i].value or r[i].link for r in table.rows[:3] if r[i].value or r[i].link]
        columns.append({"index": i, "header": h, "mapping": m, "custom": f"custom:{importer.slug(h)}",
                        "samples": samples})
    return templates.TemplateResponse(request, "import_mapping.html", base_context(
        request, token=token, meta=meta, table=table, columns=columns, choices=_field_choices(),
        errors=[]))


def _read_mapping(form, n: int) -> list[str]:
    return [form.get(f"map_{i}", "ignore") for i in range(n)]


@router.post("/import/{token}/preview")
async def import_preview(request: Request, token: str):
    path, meta = _upload(token)
    form = await request.form()
    sheet = form.get("sheet") or None
    table = importer.read_table(path, sheet)
    mapping = _read_mapping(form, len(table.headers))
    errors = importer.validate_mapping(mapping)
    if errors:
        columns = [{"index": i, "header": h, "mapping": m, "custom": f"custom:{importer.slug(h)}",
                    "samples": []} for i, (h, m) in enumerate(zip(table.headers, mapping))]
        return templates.TemplateResponse(request, "import_mapping.html", base_context(
            request, token=token, meta=meta, table=table, columns=columns,
            choices=_field_choices(), errors=errors), status_code=422)
    with get_session() as s:
        plan = importer.plan_import(s, table, mapping)
    return templates.TemplateResponse(request, "import_preview.html", base_context(
        request, token=token, meta=meta, sheet=table.sheet, plan=plan, mapping=mapping))


@router.post("/import/{token}/commit")
async def import_commit(request: Request, token: str):
    path, meta = _upload(token)
    form = await request.form()
    table = importer.read_table(path, form.get("sheet") or None)
    mapping = _read_mapping(form, len(table.headers))
    if importer.validate_mapping(mapping):
        raise HTTPException(400, "Correspondance des colonnes invalide.")
    source = f"{meta['filename']} – importé le {fmt_local(utcnow())}"
    with get_session() as s:
        # On recalcule le plan au moment de valider : la base a pu changer depuis l'aperçu.
        plan = importer.plan_import(s, table, mapping)
        counts = importer.apply_plan(s, plan, source)
        s.commit()
    _discard(token)
    return RedirectResponse(f"/contacts?imported={counts['new']}-{counts['update']}-{counts['ignore']}",
                            status_code=303)


@router.post("/import/{token}/cancel")
def import_cancel(token: str):
    if TOKEN_RE.match(token):
        _discard(token)
    return RedirectResponse("/contacts", status_code=303)


# ------------------------------------------------------------- liste d'exclusion

@router.get("/exclusions")
def exclusions(request: Request, error: str = "", ok: str = ""):
    with get_session() as s:
        rows = list(s.scalars(select(Suppression).order_by(Suppression.created_at.desc())))
    return templates.TemplateResponse(request, "exclusions.html", base_context(
        request, rows=rows, error=error, ok=ok, manual_reason=MANUAL_REASON,
        hash_prefix=suppression.HASH_PREFIX))


@router.post("/exclusions/add")
async def exclusions_add(request: Request):
    form = await request.form()
    entry = suppression.normalize_entry(form.get("entry", ""))
    if entry is None:
        return exclusions(request, error="Saisissez une adresse (nom@domaine.ma) ou un domaine (domaine.ma).")
    note = (form.get("note") or "").strip()
    reason = MANUAL_REASON + (f" – {note}" if note else "")
    with get_session() as s:
        added = suppression.add(s, entry, reason)
        # Les contacts concernés passent en « Ne plus contacter » et leurs séquences s'arrêtent.
        affected = 0
        for c in s.scalars(select(Contact).where(Contact.global_status == "active")):
            if suppression.is_suppressed(c.email, {entry}):
                cs.set_do_not_contact(s, c)
                affected += 1
        s.commit()
    msg = (f"« {entry} » ajouté" if added else f"« {entry} » était déjà dans la liste")
    if affected:
        msg += f" ; {affected} contact(s) passé(s) en « Ne plus contacter »"
    return RedirectResponse("/contacts/exclusions?" + urlencode({"ok": msg}), status_code=303)


@router.post("/exclusions/{sid}/delete")
def exclusions_delete(sid: int):
    with get_session() as s:
        row = s.get(Suppression, sid)
        # Seuls les ajouts manuels peuvent être retirés : un STOP ou un effacement est définitif.
        if row is None or not row.reason.startswith(MANUAL_REASON):
            raise HTTPException(403, "Cette entrée ne peut pas être retirée (STOP ou effacement).")
        s.delete(row)
        s.commit()
    return RedirectResponse("/contacts/exclusions?" + urlencode({"ok": "Entrée retirée"}), status_code=303)


# ------------------------------------------------------------------ fiche contact

def _get_contact(s, contact_id: int) -> Contact:
    c = s.get(Contact, contact_id)
    if c is None:
        raise HTTPException(404, "Contact introuvable.")
    return c


@router.get("/{contact_id:int}")
def contact_detail(request: Request, contact_id: int, error: str = "", ok: str = ""):
    with get_session() as s:
        c = _get_contact(s, contact_id)
        ctx = base_context(
            request, c=c, timeline=cs.timeline(s, c), enrollments=cs.enrollments_of(s, c),
            suppressed=suppression.is_suppressed_db(s, c.email), status_labels=cs.STATUS_LABELS,
            category=cs.reliability_category(c.email_reliability), active_enr=cs.ACTIVE_ENROLLMENT,
            custom_labels=settings_store.get(s, "custom_field_labels"),
            error=error, ok=ok)
    return templates.TemplateResponse(request, "contact_detail.html", ctx)


def _back(contact_id: int, **params) -> RedirectResponse:
    # urlencode : les messages contiennent espaces, accents et guillemets.
    q = urlencode(params)
    return RedirectResponse(f"/contacts/{contact_id}" + (f"?{q}" if q else ""), status_code=303)


@router.post("/{contact_id:int}/notes")
async def contact_notes(request: Request, contact_id: int):
    form = await request.form()
    with get_session() as s:
        c = _get_contact(s, contact_id)
        c.notes = (form.get("notes") or "").replace("\r\n", "\n").strip()
        s.commit()
    return _back(contact_id, ok="Notes enregistrées")


@router.post("/{contact_id:int}/do-not-contact")
def contact_dnc(contact_id: int):
    with get_session() as s:
        cs.set_do_not_contact(s, _get_contact(s, contact_id))
        s.commit()
    return _back(contact_id, ok="Contact marqué « Ne plus contacter »")


@router.post("/{contact_id:int}/reactivate")
def contact_reactivate(contact_id: int):
    with get_session() as s:
        try:
            cs.reactivate(s, _get_contact(s, contact_id))
        except cs.ReactivationRefused as exc:
            return _back(contact_id, error=str(exc))
        s.commit()
    return _back(contact_id, ok="Contact réactivé")


@router.post("/{contact_id:int}/enrollments/{enrollment_id:int}/remove")
def contact_remove_enrollment(contact_id: int, enrollment_id: int):
    with get_session() as s:
        done = cs.remove_from_campaign(s, _get_contact(s, contact_id), enrollment_id)
        s.commit()
    return _back(contact_id, **({"ok": "Retiré de la campagne"} if done else {"error": "Inscription introuvable ou déjà arrêtée"}))


@router.post("/{contact_id:int}/erase")
async def contact_erase(request: Request, contact_id: int):
    form = await request.form()
    if (form.get("confirm") or "").strip().upper() != "EFFACER":
        return _back(contact_id, error="Tapez EFFACER pour confirmer l'effacement définitif.")
    with get_session() as s:
        cs.erase(s, _get_contact(s, contact_id))
        s.commit()
    return RedirectResponse("/contacts?erased=1", status_code=303)

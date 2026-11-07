"""Pages Séquences : liste, éditeur, blocs de contenu, aperçu par contact."""
import logging
from urllib.parse import urlencode

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from starlette.concurrency import run_in_threadpool

from app import credentials, render
from app import sequences_service as ss
from app.db import get_session
from app.mail import compose, transport
from app.mailbox_service import as_form_values, get_primary, server_config
from app.models import ContentBlock, Contact, EventLog, Sequence, Step, StepVariant
from app.seed import SECTOR_BLOCKS, TARGET_BLOCKS
from app.web.templating import base_context, templates

router = APIRouter(prefix="/sequences")
log = logging.getLogger(__name__)


def _redirect(path: str, **params) -> RedirectResponse:
    return RedirectResponse(path + (f"?{urlencode(params)}" if params else ""), status_code=303)


def _get_seq(s, seq_id: int) -> Sequence:
    seq = s.get(Sequence, seq_id)
    if seq is None:
        raise HTTPException(404, "Séquence introuvable.")
    return seq


# ---------------------------------------------------------------------- liste

@router.get("")
def sequences_list(request: Request):
    with get_session() as s:
        rows = [(seq, len(ss.steps_of(s, seq)), ss.campaigns_using(s, seq))
                for seq in s.scalars(select(Sequence).order_by(Sequence.created_at))]
        todo = [b.key for b in s.scalars(select(ContentBlock)) if render.TODO_MARKER in b.body]
    return templates.TemplateResponse(request, "sequences_list.html", base_context(
        request, rows=rows, todo_blocks=todo, ok=request.query_params.get("ok", "")))


@router.post("/new")
async def sequence_new(request: Request):
    form = await request.form()
    name = (form.get("name") or "").strip() or "Nouvelle séquence"
    with get_session() as s:
        seq = ss.create_sequence(s, name)
        s.commit()
        return _redirect(f"/sequences/{seq.id}")


# ---------------------------------------------------------------------- blocs

@router.get("/blocks")
def blocks_page(request: Request):
    with get_session() as s:
        all_blocks = list(s.scalars(select(ContentBlock)))
    order = list(TARGET_BLOCKS) + list(SECTOR_BLOCKS)
    all_blocks.sort(key=lambda b: (b.kind != "target", order.index(b.key) if b.key in order else 99))
    labels = {**TARGET_BLOCKS, **SECTOR_BLOCKS}
    return templates.TemplateResponse(request, "blocks.html", base_context(
        request, blocks=all_blocks, labels=labels, todo=render.TODO_MARKER, known_vars=render.KNOWN_VARS,
        ok=request.query_params.get("ok", "")))


@router.post("/blocks/{block_id:int}")
async def block_save(request: Request, block_id: int):
    form = await request.form()
    with get_session() as s:
        b = s.get(ContentBlock, block_id)
        if b is None:
            raise HTTPException(404)
        b.body = (form.get("body") or "").replace("\r\n", "\n").strip()
        s.commit()
        key = b.key
    return RedirectResponse(f"/sequences/blocks?{urlencode({'ok': f'Bloc {key} enregistré'})}#bloc-{key}",
                            status_code=303)


# --------------------------------------------------------------------- éditeur

@router.get("/{seq_id:int}")
def sequence_edit(request: Request, seq_id: int):
    with get_session() as s:
        seq = _get_seq(s, seq_id)
        steps = [(st, ss.variants_of(s, st)) for st in ss.steps_of(s, seq)]
        cumul, total = [], 0
        for st, _ in steps:
            total += st.delay_days
            cumul.append(total)
        ctx = base_context(request, seq=seq, steps=steps, cumul=cumul, used_by=ss.campaigns_using(s, seq),
                           known_vars=render.KNOWN_VARS, ok=request.query_params.get("ok", ""),
                           error=request.query_params.get("error", ""))
    return templates.TemplateResponse(request, "sequence_edit.html", ctx)


@router.post("/{seq_id:int}")
async def sequence_save(request: Request, seq_id: int):
    form = await request.form()
    with get_session() as s:
        seq = _get_seq(s, seq_id)
        seq.name = (form.get("name") or "").strip() or seq.name
        for st in ss.steps_of(s, seq):
            p = f"{st.id}_"
            st.body_template = (form.get(p + "body") or "").replace("\r\n", "\n").strip()
            if st.position == 1:
                st.delay_days, st.same_thread = 0, False  # la première étape part dès l'activation
            else:
                raw = (form.get(p + "delay") or "0").strip()
                st.delay_days = max(0, min(int(raw), 90)) if raw.isdigit() else st.delay_days
                st.same_thread = form.get(p + "thread") == "on"
            st.business_days = form.get(p + "business") == "on"

            variants = ss.variants_of(s, st)
            wanted = {"A": (form.get(p + "subject_A") or "").strip()}
            if st.position == 1:
                wanted["B"] = (form.get(p + "subject_B") or "").strip()
            for label, subject in wanted.items():
                v = variants.get(label)
                if label == "B" and not subject:
                    if v is not None:
                        s.delete(v)  # plus d'objet B : on revient à un seul objet
                    continue
                if st.position > 1 and st.same_thread and not subject:
                    continue  # relance dans le fil : l'objet est « Re: … »
                if v is None:
                    s.add(StepVariant(step_id=st.id, label=label, subject_template=subject))
                else:
                    v.subject_template = subject
        s.add(EventLog(level="info", entity="sequence", entity_id=seq.id, text=f"Séquence « {seq.name} » modifiée"))
        s.commit()
    return _redirect(f"/sequences/{seq_id}", ok="Séquence enregistrée")


@router.post("/{seq_id:int}/steps/add")
def step_add(seq_id: int):
    with get_session() as s:
        seq = _get_seq(s, seq_id)
        steps = ss.steps_of(s, seq)
        if len(steps) >= 8:
            return _redirect(f"/sequences/{seq_id}", error="8 étapes maximum.")
        s.add(Step(sequence_id=seq.id, position=len(steps) + 1, delay_days=4, business_days=True,
                   same_thread=True, body_template=""))
        s.commit()
    return _redirect(f"/sequences/{seq_id}", ok="Étape ajoutée")


@router.post("/{seq_id:int}/steps/{step_id:int}/delete")
def step_delete(seq_id: int, step_id: int):
    with get_session() as s:
        seq = _get_seq(s, seq_id)
        st = s.get(Step, step_id)
        if st is None or st.sequence_id != seq.id:
            raise HTTPException(404)
        if st.position == 1:
            return _redirect(f"/sequences/{seq_id}", error="La première étape ne peut pas être supprimée.")
        if ss.campaigns_using(s, seq):
            return _redirect(f"/sequences/{seq_id}",
                             error="Séquence utilisée par une campagne : supprimer une étape décalerait les envois en cours.")
        s.delete(st)
        s.flush()
        ss.renumber(s, seq)
        s.commit()
    return _redirect(f"/sequences/{seq_id}", ok="Étape supprimée")


@router.post("/{seq_id:int}/delete")
def sequence_delete(seq_id: int):
    with get_session() as s:
        seq = _get_seq(s, seq_id)
        if ss.campaigns_using(s, seq):
            return _redirect(f"/sequences/{seq_id}", error="Séquence utilisée par une campagne : suppression impossible.")
        for st in ss.steps_of(s, seq):
            s.delete(st)
        s.delete(seq)
        s.commit()
    return _redirect("/sequences", ok="Séquence supprimée")


# ---------------------------------------------------------------------- aperçu

def _contacts_for_select(s) -> list[Contact]:
    return list(s.scalars(select(Contact).order_by(Contact.company, Contact.last_name)))


@router.get("/{seq_id:int}/preview")
def sequence_preview(request: Request, seq_id: int, contact_id: int | None = None, variant: str = ""):
    with get_session() as s:
        seq = _get_seq(s, seq_id)
        contacts = _contacts_for_select(s)
        contact = s.get(Contact, contact_id) if contact_id else (contacts[0] if contacts else None)
        first = ss.steps_of(s, seq)[:1]
        labels = sorted(ss.variants_of(s, first[0])) if first else []
        previews = ss.preview(s, seq, contact, variant or None) if contact else []
        shown_variant = (variant if variant in labels else ss.preview_variant(contact, labels)) if contact else ""
        mb = get_primary(s)
        ctx = base_context(request, seq=seq, contacts=contacts, contact=contact, previews=previews,
                           labels=labels, variant=shown_variant, mailbox_email=mb.email if mb else None,
                           ok=request.query_params.get("ok", ""), error=request.query_params.get("error", ""))
    return templates.TemplateResponse(request, "sequence_preview.html", ctx)


def _send_preview_messages(cfg, messages) -> None:
    with transport.open_smtp(cfg) as smtp:
        for m in messages:
            smtp.send_message(m)


@router.post("/{seq_id:int}/preview/send")
async def sequence_preview_send(request: Request, seq_id: int):
    """« M'envoyer cet aperçu » : toutes les étapes, à l'adresse d'Omar uniquement,
    enchaînées dans un même fil comme le seront les vraies relances."""
    form = await request.form()
    contact_id = int(form.get("contact_id") or 0)
    variant = form.get("variant") or ""
    back = dict(contact_id=contact_id, variant=variant)
    with get_session() as s:
        seq = _get_seq(s, seq_id)
        contact = s.get(Contact, contact_id)
        mb = get_primary(s)
        if contact is None or mb is None:
            return _redirect(f"/sequences/{seq_id}/preview", error="Contact ou boîte mail manquant.", **back)
        password = credentials.get_password(mb.email)
        if not password:
            return _redirect(f"/sequences/{seq_id}/preview", error="Mot de passe de la boîte non enregistré.", **back)
        cfg = server_config(as_form_values(mb), password)
        previews = ss.preview(s, seq, contact, variant or None)
        messages, chain = [], []
        for p in previews:
            mid = compose.new_message_id(mb.email)
            subject = compose.preview_subject(f"[Étape {p.position}] {p.subject or '(sans objet)'}", contact.email)
            messages.append(compose.build_message(
                from_name=mb.display_name, from_email=mb.email, to_email=mb.email,  # jamais au contact
                subject=subject, body=p.body, message_id=mid,
                in_reply_to=chain[-1] if (chain and p.same_thread) else None,
                references=list(chain) if (chain and p.same_thread) else None))
            chain.append(mid)
        s.add(EventLog(level="info", entity="sequence", entity_id=seq.id,
                       text=f"Aperçu de « {seq.name} » ({len(messages)} étape(s)) envoyé à {mb.email}"))
        s.commit()
    try:
        await run_in_threadpool(_send_preview_messages, cfg, messages)
    except Exception as exc:  # noqa: BLE001
        log.warning("Envoi de l'aperçu impossible : %s", exc)
        return _redirect(f"/sequences/{seq_id}/preview",
                         error=transport.explain_error(exc, "SMTP", cfg.smtp_host, cfg.smtp_port), **back)
    return _redirect(f"/sequences/{seq_id}/preview", ok=f"{len(messages)} email(s) d'aperçu envoyé(s) à {cfg.email}", **back)

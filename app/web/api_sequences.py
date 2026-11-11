"""API V2 : séquences (éditeur en timeline), blocs de contenu, aperçu par contact."""
from __future__ import annotations

import re

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from starlette.concurrency import run_in_threadpool

from app import attachments_service, credentials, render, vocab
from app import campaigns_service as camp_svc
from app.models import Campaign
from app import sequences_service as ss
from app.db import get_session
from app.mail import compose, transport
from app.mailbox_service import as_form_values, get_primary, server_config
from app.models import ContentBlock, Contact, EventLog, Sequence, Step, StepVariant, StepAttachment
from app.seed import SECTOR_BLOCKS, TARGET_BLOCKS
from app.web.api_common import contact_ref, iso, not_found, require_admin_or_owner

router = APIRouter(prefix="/api")
MAX_STEPS = 8


def _seq(s, sid: int) -> Sequence:
    seq = s.get(Sequence, sid)
    if seq is None:
        raise not_found("Séquence")
    return seq


def _seq_editable(s, sid: int) -> Sequence:
    seq = _seq(s, sid)
    require_admin_or_owner(seq.owner_id, "Modèle commun à l'équipe : seul l'administrateur peut le modifier. Dupliquez-le pour en faire votre version.")
    return seq


def _step_json(s, st: Step) -> dict:
    v = ss.variants_of(s, st)
    return {"id": st.id, "position": st.position, "delay_days": st.delay_days, "business_days": st.business_days,
            "weekday": st.weekday, "send_time": st.send_time, "same_thread": st.same_thread, "body": st.body_template,
            "subject_a": v["A"].subject_template if "A" in v else "",
            "subject_b": v["B"].subject_template if "B" in v else "",
            "attachments": [attachments_service.as_json(a) for a in attachments_service.of_step(s, st.id)]}


CATEGORIES = {"prospection": "Prospection", "gestion": "Gestion", "souscription": "Souscription"}


def _sequence_json(s, seq: Sequence) -> dict:
    from app.current import is_admin, user_id
    return {"id": seq.id, "name": seq.name, "category": seq.category, "branch": seq.branch, "campaigns": ss.campaigns_using(s, seq),
            "steps": [_step_json(s, st) for st in ss.steps_of(s, seq)],
            # V3 : modèle commun (modifiable par l'administrateur) ou personnel (par son auteur)
            "shared": seq.owner_id is None, "editable": is_admin() or seq.owner_id == user_id()}


@router.get("/sequences")
def sequences():
    from app.current import is_admin, user_id
    with get_session() as s:
        todo = sorted(b.key for b in s.scalars(select(ContentBlock)) if render.TODO_MARKER in b.body)
        # V3 : comptes groupés en 2 requêtes (au lieu de 3 par séquence ; la base est à distance)
        steps = {sid: (n, days or 0) for sid, n, days in s.execute(
            select(Step.sequence_id, func.count(Step.id), func.sum(Step.delay_days)).group_by(Step.sequence_id))}
        used = dict(s.execute(select(Campaign.sequence_id, func.count(Campaign.id)).group_by(Campaign.sequence_id)).all())
        return {"todo_blocks": todo, "items": [
            {"id": q.id, "name": q.name, "category": q.category, "branch": q.branch, "steps": steps.get(q.id, (0, 0))[0],
             "campaigns": used.get(q.id, 0),
             "created_at": iso(q.created_at),
             # V3 : modèle commun (owner vide) ou personnel, visible par son auteur seulement
             "shared": q.owner_id is None, "editable": is_admin() or q.owner_id == user_id(),
             "total_days": steps.get(q.id, (0, 0))[1]}
            for q in s.scalars(select(Sequence).order_by(Sequence.created_at))],
            "categories": [{"value": k, "label": v} for k, v in CATEGORIES.items()]}


class NewSequence(BaseModel):
    name: str = Field(default="Nouvelle séquence", max_length=200)
    category: str = Field(default="prospection", pattern="^(prospection|gestion|souscription)$")
    steps: int = Field(default=3, ge=1, le=3)  # V2.23 : 1 = un modèle d'email à réutiliser (bouton Modèles)


@router.post("/sequences")
def sequence_create(body: NewSequence):
    with get_session() as s:
        seq = ss.create_sequence(s, body.name.strip() or "Nouvelle séquence", body.steps)
        seq.category = body.category
        s.commit()
        return {"id": seq.id}


@router.post("/sequences/{sid:int}/duplicate")
def sequence_duplicate(sid: int):
    with get_session() as s:
        src = _seq(s, sid)
        from app.current import user_id
        copy = Sequence(name=f"{src.name} (copie)", category=src.category, branch=src.branch, owner_id=user_id())
        s.add(copy)
        s.flush()
        for st in ss.steps_of(s, src):
            n = Step(sequence_id=copy.id, position=st.position, delay_days=st.delay_days,
                     business_days=st.business_days, weekday=st.weekday, send_time=st.send_time,
                     same_thread=st.same_thread, body_template=st.body_template)
            s.add(n)
            s.flush()
            for v in ss.variants_of(s, st).values():
                s.add(StepVariant(step_id=n.id, label=v.label, subject_template=v.subject_template))
            for a in attachments_service.of_step(s, st.id):
                s.add(StepAttachment(step_id=n.id, attachment_id=a.id))
        s.commit()
        return {"id": copy.id}


@router.post("/sequences/{sid:int}/share")
def sequence_share(sid: int):
    """V3.3.3 : l'administrateur rend commun un de SES modèles personnels (toute l'équipe le voit)."""
    from app.current import is_admin, user_id
    with get_session() as s:
        seq = _seq(s, sid)
        if not is_admin() or seq.owner_id != user_id():
            raise HTTPException(403, "Seul l'administrateur peut partager un de ses modèles avec l'équipe.")
        seq.owner_id = None
        s.commit()
        return _sequence_json(s, seq)


@router.post("/sequences/{sid:int}/unshare")
def sequence_unshare(sid: int):
    """V3.5 : l'administrateur repasse un modèle commun en personnel (lui seul le voit ensuite).
    Refusé si un collègue l'utilise dans une campagne : il ne doit pas perdre l'accès à son modèle."""
    from app import scope
    from app.current import is_admin, user_id
    with get_session() as s:
        seq = _seq(s, sid)
        if not is_admin():
            raise HTTPException(403, "Seul l'administrateur peut retirer un modèle de l'équipe.")
        if seq.owner_id is not None:
            raise HTTPException(409, "Ce modèle est déjà personnel.")
        mine = scope.mailbox_id_of(s, user_id()) if user_id() is not None else None
        others = s.scalar(select(func.count(Campaign.id)).where(Campaign.sequence_id == seq.id, Campaign.mailbox_id != mine)
                          .execution_options(oddo_all=True)) or 0
        if others:
            raise HTTPException(409, f"Un collègue l'utilise dans {others} campagne{'s' if others > 1 else ''} : "
                                     "elle reste commune. Pour une version perso, dupliquez-la.")
        seq.owner_id = user_id()
        s.commit()
        return _sequence_json(s, seq)


@router.get("/sequences/{sid:int}")
def sequence_get(sid: int):
    with get_session() as s:
        return {**_sequence_json(s, _seq(s, sid)), "variables": render.KNOWN_VARS,
                "custom_fields": _custom_fields(s)}


def _custom_fields(s) -> list[str]:
    keys: set[str] = set()
    for (custom,) in s.execute(select(Contact.custom)):
        keys.update((custom or {}).keys())
    return sorted(keys)


class StepIn(BaseModel):
    id: int
    delay_days: int = Field(ge=0, le=90)
    business_days: bool = True
    weekday: int | None = Field(default=None, ge=0, le=4)            # V2.5 : lundi (0) à vendredi (4)
    send_time: str | None = Field(default=None, pattern=r"^([01]\d|2[0-3]):[0-5]\d$")  # « 10:00 »
    same_thread: bool = True
    attachment_ids: list[int] | None = None  # V2.8 : None = ne pas toucher aux pièces jointes
    body: str = ""
    subject_a: str = ""
    subject_b: str = ""


class SequenceIn(BaseModel):
    name: str = Field(max_length=200)
    category: str | None = Field(default=None, pattern="^(prospection|gestion|souscription)$")
    branch: str | None = Field(default=None, max_length=40)
    steps: list[StepIn]


@router.put("/sequences/{sid:int}")
def sequence_save(sid: int, body: SequenceIn):
    """Enregistrement complet de la séquence (appelé automatiquement pendant la frappe)."""
    with get_session() as s:
        seq = _seq_editable(s, sid)
        seq.name = body.name.strip() or seq.name
        if body.category and body.category != seq.category:
            if ss.campaigns_using(s, seq):
                raise HTTPException(409, "Séquence déjà utilisée par une campagne : son type ne peut plus changer (dupliquez-la).")
            seq.category = body.category
        if body.branch is not None:
            seq.branch = body.branch.strip() or None
        steps = {st.id: st for st in ss.steps_of(s, seq)}
        for item in body.steps:
            st = steps.get(item.id)
            if st is None:
                raise HTTPException(409, "La séquence a changé entre-temps : rechargez la page.")
            st.body_template = item.body.replace("\r\n", "\n").strip()
            st.business_days = item.business_days
            st.weekday, st.send_time = item.weekday, item.send_time or None
            if item.attachment_ids is not None:
                try:
                    attachments_service.set_step(s, st.id, item.attachment_ids)
                except attachments_service.AttachmentError as exc:
                    raise HTTPException(422, str(exc)) from None
            if st.position == 1:
                st.delay_days, st.same_thread = 0, False
            else:
                st.delay_days, st.same_thread = item.delay_days, item.same_thread
            variants = ss.variants_of(s, st)
            wanted = {"A": item.subject_a.strip()}
            if st.position == 1:
                wanted["B"] = item.subject_b.strip()
            for label, subject in wanted.items():
                v = variants.get(label)
                if label == "B" and not subject:
                    if v is not None:
                        s.delete(v)
                    continue
                if st.position > 1 and st.same_thread and not subject:
                    continue
                if v is None:
                    s.add(StepVariant(step_id=st.id, label=label, subject_template=subject))
                else:
                    v.subject_template = subject
        s.commit()
        return _sequence_json(s, seq)


@router.post("/sequences/{sid:int}/steps")
def step_add(sid: int):
    with get_session() as s:
        seq = _seq_editable(s, sid)
        steps = ss.steps_of(s, seq)
        if len(steps) >= MAX_STEPS:
            raise HTTPException(400, f"{MAX_STEPS} étapes maximum.")
        s.add(Step(sequence_id=seq.id, position=len(steps) + 1, delay_days=4, business_days=True,
                   same_thread=True, body_template='Bonjour {{ prenom | "Madame, Monsieur" }},\n\n'))
        s.commit()
        return _sequence_json(s, seq)


@router.delete("/sequences/{sid:int}/steps/{step_id:int}")
def step_delete(sid: int, step_id: int):
    with get_session() as s:
        seq = _seq_editable(s, sid)
        st = s.get(Step, step_id)
        if st is None or st.sequence_id != seq.id:
            raise not_found("Étape")
        if st.position == 1:
            raise HTTPException(400, "La première étape ne peut pas être supprimée.")
        if ss.campaigns_using(s, seq):
            raise HTTPException(400, "Séquence utilisée par une campagne : supprimer une étape décalerait les envois.")
        s.delete(st)
        s.flush()
        ss.renumber(s, seq)
        s.commit()
        return _sequence_json(s, seq)


@router.delete("/sequences/{sid:int}")
def sequence_delete(sid: int):
    with get_session() as s:
        seq = _seq_editable(s, sid)
        if ss.campaigns_using(s, seq):
            raise HTTPException(400, "Séquence utilisée par une campagne (la vôtre ou celle d'un collègue) : suppression impossible.")
        s.delete(seq)  # étapes et variantes supprimées par la base (ON DELETE CASCADE), comme en V1
        s.commit()
    return {"ok": True}


# ----------------------------------------------------------------------- aperçu

@router.get("/sequences/{sid:int}/preview")
def sequence_preview(sid: int, contact_id: int | None = None, variant: str = ""):
    with get_session() as s:
        seq = _seq(s, sid)
        contact = s.get(Contact, contact_id) if contact_id else s.scalars(
            select(Contact).where(Contact.global_status == "active").order_by(Contact.company)).first()
        first = ss.steps_of(s, seq)[:1]
        labels = sorted(ss.variants_of(s, first[0])) if first else []
        if contact is None:
            return {"contact": None, "labels": labels, "variant": None, "steps": []}
        shown = variant if variant in labels else ss.preview_variant(contact, labels)
        return {"contact": contact_ref(contact), "labels": labels, "variant": shown,
                "steps": [{"position": p.position, "subject": p.subject, "body": p.body, "planned_at": iso(p.planned_at),
                           "same_thread": p.same_thread, "problems": p.problems, "warnings": p.warnings}
                          for p in ss.preview(s, seq, contact, shown or None)]}


@router.get("/contacts-picker")
def contacts_picker(q: str = ""):
    """Liste courte pour choisir le contact de l'aperçu."""
    with get_session() as s:
        stmt = select(Contact).order_by(Contact.company, Contact.last_name)
        # Chaque mot doit se trouver quelque part : « gestionnaire sanlam » trouve le
        # gestionnaire de chez Sanlam (V2.3 : le poste compte aussi).
        for word in q.split()[:6]:
            like = f"%{word}%"
            stmt = stmt.where(Contact.company.ilike(like) | Contact.first_name.ilike(like) | Contact.last_name.ilike(like)
                              | Contact.email.ilike(like) | Contact.job_title.ilike(like))
        return [{**contact_ref(c), "job_title": c.job_title} for c in s.scalars(stmt.limit(50))]


class PreviewSendIn(BaseModel):
    contact_id: int
    variant: str = ""


@router.post("/sequences/{sid:int}/preview/send")
async def preview_send(sid: int, body: PreviewSendIn):
    with get_session() as s:
        seq = _seq(s, sid)
        contact, mb = s.get(Contact, body.contact_id), get_primary(s)
        if contact is None or mb is None:
            raise HTTPException(400, "Contact ou boîte mail manquant.")
        password = credentials.get_password(mb.email)
        if not password:
            raise HTTPException(400, "Mot de passe de la boîte non enregistré.")
        cfg = server_config(as_form_values(mb), password)
        messages, chain = [], []
        steps = {st.position: st for st in ss.steps_of(s, seq)}
        for p in ss.preview(s, seq, contact, body.variant or None):
            mid = compose.new_message_id(mb.email)
            subject = compose.preview_subject(f"[Étape {p.position}] {p.subject or '(sans objet)'}", contact.email)
            messages.append(compose.build_message(
                from_name=mb.display_name, from_email=mb.email, to_email=mb.email, subject=subject, body=p.body,
                message_id=mid, in_reply_to=chain[-1] if (chain and p.same_thread) else None,
                references=list(chain) if (chain and p.same_thread) else None,
                attachments=attachments_service.of_step(s, steps[p.position].id)))
            chain.append(mid)
        s.add(EventLog(level="info", entity="sequence", entity_id=seq.id,
                       text=f"Aperçu de « {seq.name} » ({len(messages)} étape(s)) envoyé à {mb.email}"))
        s.commit()

    def send():
        with transport.open_smtp(cfg) as smtp:
            for m in messages:
                smtp.send_message(m)
    try:
        await run_in_threadpool(send)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(502, transport.explain_error(exc, "SMTP", cfg.smtp_host, cfg.smtp_port)) from None
    return {"sent": len(messages), "to": cfg.email}


# ------------------------------------------------------------------------ blocs

GENERIC_LABELS = {"target": "Générique (sans fonction)", "sector": "Générique (sans secteur)"}


def _block_json(s, b: ContentBlock, labels: dict) -> dict:
    generic = b.key == render.GENERIC
    return {"id": b.id, "kind": b.kind, "key": b.key, "body": b.body, "todo": render.TODO_MARKER in b.body,
            "label": GENERIC_LABELS[b.kind] if generic else b.label or labels.get(b.key, b.key),
            "custom": bool(b.label), "generic": generic, "variant_of": b.variant_of,
            "used": vocab.profile_usage(s, b), "campaigns": vocab.campaigns_using_block(s, b)}


@router.get("/blocks")
def blocks():
    labels = {**TARGET_BLOCKS, **SECTOR_BLOCKS}
    order = list(TARGET_BLOCKS) + list(SECTOR_BLOCKS)
    with get_session() as s:
        all_ = list(s.scalars(select(ContentBlock)))
        roots = {b.key: i for i, b in enumerate(sorted(all_, key=lambda b: order.index(b.key) if b.key in order else 99))}

        def rank(b: ContentBlock):  # variantes juste après leur texte d'origine, générique en dernier
            root = b.variant_of or b.key
            return (b.kind != "target", b.key == render.GENERIC, order.index(root) if root in order else 50 + roots.get(root, 0),
                    b.variant_of is not None, b.id)
        return [_block_json(s, b, labels) for b in sorted(all_, key=rank)]


class VariantIn(BaseModel):
    number: int | None = None  # V3.7 : variante d'un lot précis (4 → FIN4)


@router.post("/blocks/{bid:int}/variant")
def block_variant(bid: int, body: VariantIn | None = None):
    """V3.4 : une variante du texte (« Finance 2 »), à rédiger autrement pour tester."""
    with get_session() as s:
        b = s.get(ContentBlock, bid)
        if b is None:
            raise not_found("Texte")
        try:
            v = vocab.add_variant(s, b, body.number if body else None)
        except vocab.ProfileError as exc:
            raise HTTPException(422, {"errors": {"label": str(exc)}}) from None
        if body and body.number:  # V3.7 : le lot visé la reçoit aussi dans les campagnes déjà lancées
            from app.models import Campaign
            for camp in s.scalars(select(Campaign).where(Campaign.status.in_(("active", "paused")))):
                ss.assign_codes(s, camp)
        s.commit()
        return _block_json(s, v, {**TARGET_BLOCKS, **SECTOR_BLOCKS})


class NewBlock(BaseModel):
    kind: str = Field(pattern="^(target|sector)$")
    label: str = Field(max_length=120)


@router.post("/blocks")
def block_create(body: NewBlock):
    """V2.9 : nouvelle fonction ou nouveau secteur, avec son texte à rédiger."""
    with get_session() as s:
        try:
            b = vocab.add_profile(s, body.kind, body.label)
        except vocab.ProfileError as exc:
            raise HTTPException(422, {"errors": {"label": str(exc)}}) from None
        s.commit()
        return {"id": b.id, "kind": b.kind, "key": b.key, "label": b.label, "body": b.body, "todo": True,
                "custom": True, "generic": False, "variant_of": None, "used": 0, "campaigns": 0}


@router.delete("/blocks/{bid:int}")
def block_delete(bid: int):
    require_admin_or_owner(None, "Textes communs à l'équipe : seul l'administrateur peut les supprimer.")
    with get_session() as s:
        b = s.get(ContentBlock, bid)
        if b is None:
            raise not_found("Texte")
        try:
            vocab.remove_profile(s, b)
        except vocab.ProfileError as exc:
            raise HTTPException(409, str(exc)) from None
        s.commit()
        return {"ok": True}


class BlockIn(BaseModel):
    body: str


@router.put("/blocks/{bid:int}")
def block_save(bid: int, body: BlockIn):
    require_admin_or_owner(None, "Textes communs à l'équipe : seul l'administrateur peut les modifier.")
    with get_session() as s:
        b = s.get(ContentBlock, bid)
        if b is None:
            raise not_found("Bloc")
        b.body = body.body.replace("\r\n", "\n").strip()
        s.commit()
        return {"id": b.id, "todo": render.TODO_MARKER in b.body}


# ------------------------------------------------------------------ envoyer une séquence (V2.9)

@router.get("/sequences/{sid:int}/draft")
def sequence_draft(sid: int, contact_id: int):
    """Les emails de la séquence déjà écrits pour CE contact (sans signature ni ligne STOP),
    pour les personnaliser avant l'envoi."""
    with get_session() as s:
        seq, c = _seq(s, sid), s.get(Contact, contact_id)
        if c is None:
            raise not_found("Contact")
        ctx = ss.build_context(s, c)
        steps, out, first_subject = ss.steps_of(s, seq), [], ""
        for st in steps:
            comp = ss.compose_step(ctx, st, ss.variants_of(s, st), None, first_subject, "")
            if st.position == 1:
                first_subject = comp.subject
            own = st.position == 1 or not st.same_thread
            body_text = render.render(st.body_template, ctx).text
            problems = comp.problems
            if not own:  # V2.23 : l'objet « Re: » suit le 1er email : ses [champs] se règlent là-bas
                holes = render.placeholders(body_text)
                problems = [p for p in problems if not p.startswith("À compléter")] + (
                    ["À compléter : " + ", ".join(f"[{h}]" for h in dict.fromkeys(holes))] if holes else [])
            out.append({"position": st.position, "own_subject": own,
                        "subject": comp.subject, "body": body_text,
                        "delay_days": st.delay_days, "problems": problems})
        return {"sequence": {"id": seq.id, "name": seq.name, "category": seq.category},
                "contact": contact_ref(c), "kind": c.kind, "steps": out,
                "attachments": [attachments_service.as_json(a) for a in attachments_service.of_step(s, steps[0].id)] if steps else []}


@router.get("/sequences/{sid:int}/template")
def sequence_template(sid: int, email: str = "", position: int = 1):
    """V2.21 : un email de séquence prêt à insérer dans « Nouveau message » (bouton Modèles),
    écrit pour le destinataire s'il est dans les contacts (sinon « Madame, Monsieur »).
    Les champs entre [crochets] restent à compléter."""
    from sqlalchemy import func
    with get_session() as s:
        seq = _seq(s, sid)
        addr = (email or "").split(",")[0].strip().lower()
        c = s.scalars(select(Contact).where(func.lower(Contact.email) == addr)).first() if addr else None
        ctx = ss.build_context(s, c or Contact(email=addr or "destinataire@exemple.ma"))
        steps, first_subject = ss.steps_of(s, seq), ""
        for st in steps:
            comp = ss.compose_step(ctx, st, ss.variants_of(s, st), None, first_subject, "")
            if st.position == 1:
                first_subject = comp.subject
            if st.position == position:
                return {"subject": comp.subject, "body": render.render(st.body_template, ctx).text,
                        "contact": contact_ref(c) if c else None,
                        "attachments": [attachments_service.as_json(a) for a in attachments_service.of_step(s, st.id)]}
        raise not_found("Étape")


class SendIn(BaseModel):
    contact_ids: list[int] = Field(min_length=1, max_length=500)
    overlap: bool = False
    overrides: dict | None = None  # seulement pour un contact seul
    fills: dict[str, str] | None = None  # V2.23 : [champs] remplis une fois pour toutes les personnes
    attachment_ids: list[int] = Field(default_factory=list, max_length=20)  # V2.23 : pièces pour toutes
    max_steps: int | None = Field(default=None, ge=1, le=8)  # V2.24 : n'envoyer que les N premiers emails


@router.post("/sequences/{sid:int}/send")
def sequence_send(sid: int, body: SendIn):
    """Envoie la séquence à des personnes choisies : elles entrent dans la campagne « à
    l'unité » de la séquence, avec les mêmes contrôles qu'un ajout à une campagne."""
    with get_session() as s:
        seq = _seq(s, sid)
        if not ss.steps_of(s, seq):
            raise HTTPException(409, "Cette séquence n'a aucun email.")
        try:
            camp = camp_svc.direct_campaign(s, seq)
        except camp_svc.EnrollRefused as exc:
            raise HTTPException(409, str(exc)) from None
        sent, refused = [], []
        single = len(body.contact_ids) == 1
        shared = ss.fill_overrides(s, seq, body.fills or {}, body.attachment_ids) if (body.fills or body.attachment_ids) else None
        for cid in dict.fromkeys(body.contact_ids):
            c = s.get(Contact, cid)
            if c is None:
                continue
            try:
                with s.begin_nested():
                    enr = camp_svc.enroll_one(s, camp, c, body.overlap, overrides=(body.overrides if single and body.overrides else shared),
                                             max_steps=body.max_steps)
                sent.append({"contact": contact_ref(c), "next_due_at": iso(enr.next_due_at)})
            except camp_svc.EnrollRefused as exc:
                refused.append({"contact": contact_ref(c), "reason": str(exc), "problems": exc.problems,
                                "overlap": exc.overlap})
        s.commit()
        return {"campaign": {"id": camp.id, "name": camp.name, "status": camp.status},
                "sent": sent, "refused": refused}


ANNOUNCED_ATTACHMENT = re.compile(r"ci[- ]joint|en pi[eè]ce jointe|en annexe", re.IGNORECASE)


@router.post("/sequences/{sid:int}/review")
def sequence_review(sid: int, body: SendIn):
    """V2.25 : l'aperçu exact avant l'envoi. Pour chaque personne, les emails qui partiront
    (objet, texte avec signature, pièces jointes, date prévue), calculés comme à l'envoi :
    l'inscription est jouée « à blanc » (mêmes contrôles, mêmes textes), puis rien n'est gardé."""
    from app import settings_store
    with get_session() as s:
        seq = _seq(s, sid)
        steps = ss.steps_of(s, seq)
        if not steps:
            raise HTTPException(409, "Cette séquence n'a aucun email.")
        try:
            camp = camp_svc.direct_campaign(s, seq)
        except camp_svc.EnrollRefused as exc:
            raise HTTPException(409, str(exc)) from None
        n = body.max_steps if body.max_steps and body.max_steps < len(steps) else len(steps)
        single = len(body.contact_ids) == 1
        shared = ss.fill_overrides(s, seq, body.fills or {}, body.attachment_ids) if (body.fills or body.attachment_ids) else None
        mb = get_primary(s)
        test_mode = bool(settings_store.get(s, "test_mode"))
        base_atts = {st.position: attachments_service.of_step(s, st.id) for st in steps}
        labels = sorted(ss.variants_of(s, steps[0]))
        people = []
        for cid in list(dict.fromkeys(body.contact_ids))[:50]:
            c = s.get(Contact, cid)
            if c is None:
                continue
            ov = camp_svc.clean_overrides(body.overrides if single and body.overrides else shared)
            refused, problems, overlap, start = None, [], [], None
            sp = s.begin_nested()
            try:
                enr = camp_svc.enroll_one(s, camp, c, body.overlap, overrides=ov, max_steps=body.max_steps)
                start = enr.next_due_at
            except camp_svc.EnrollRefused as exc:
                refused, problems, overlap = str(exc), exc.problems, exc.overlap
            finally:
                sp.rollback()
            emails = []
            for p in ss.preview(s, seq, c, labels[0] if labels else None, start_utc=start, overrides=ov)[:n]:
                extra = ((ov or {}).get(str(p.position)) or {}).get("attachment_ids") or []
                atts = base_atts[p.position] + [a for a in attachments_service.get_many(s, extra)
                                                if a.id not in {x.id for x in base_atts[p.position]}]
                warnings = list(p.warnings)
                if not atts and ANNOUNCED_ATTACHMENT.search(p.body):
                    warnings.append("Le texte annonce une pièce jointe (« ci-joint »), mais aucun fichier n'est joint.")
                emails.append({"position": p.position, "subject": p.subject, "body": p.body,
                               "planned_at": iso(p.planned_at), "same_thread": p.same_thread,
                               "problems": p.problems, "warnings": warnings,
                               "attachments": [attachments_service.as_json(a) for a in atts]})
            people.append({"contact": contact_ref(c), "to": c.email, "refused": refused, "problems": problems,
                           "overlap": overlap, "emails": emails})
        s.rollback()  # rien n'est enregistré
        return {"sequence": {"id": seq.id, "name": seq.name}, "steps": n, "total_steps": len(steps),
                "ab_subjects": len(labels) > 1, "test_mode": test_mode,
                "from": {"name": mb.display_name, "email": mb.email} if mb else None,
                "people": people}


@router.get("/sequences/{sid:int}/holes")
def sequence_holes(sid: int, steps: int | None = None):
    """V2.23 : les [champs] à remplir une fois quand la séquence part à plusieurs personnes.
    V2.24 : ?steps=N : seulement ceux des N premiers emails."""
    with get_session() as s:
        return {"holes": ss.template_holes(s, _seq(s, sid), steps if steps and steps > 0 else None)}


@router.get("/sequences/{sid:int}/schedule")
def sequence_schedule(sid: int):
    """V2.11 : dates indicatives de chaque email si on envoie maintenant (plages d'envoi,
    jours ouvrés, jour/heure des étapes). Le moteur peut décaler un peu (plafonds, pauses)."""
    from app.scheduling import SendWindow, planned_dates
    from app.timeutil import utcnow
    with get_session() as s:
        steps = ss.steps_of(s, _seq(s, sid))
        dates = planned_dates(SendWindow.from_settings(s), utcnow(), steps) if steps else []
        return [{"position": st.position, "planned_at": iso(d)} for st, d in zip(steps, dates)]

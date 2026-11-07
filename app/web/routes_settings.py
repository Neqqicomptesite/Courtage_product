"""Page « Réglages » : boîte mail, envoi, mode test, test de connexion."""
import logging

from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse
from starlette.concurrency import run_in_threadpool

from app import credentials, mailbox_service, settings_store
from app.db import get_session
from app.mail import transport
from app.models import EventLog
from app.web import forms
from app.web.templating import base_context, templates

router = APIRouter(prefix="/settings")
log = logging.getLogger(__name__)

DAY_NAMES = ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi", "Dimanche"]
CAP_WARNING = 50  # §4 / §8 : avertissement au-delà de 50 emails par jour


def _page(request: Request, *, mailbox_values=None, sending_values=None,
          errors=None, status_code=200, flash=None):
    with get_session() as s:
        mb = mailbox_service.get_primary(s)
        values = mailbox_values or mailbox_service.as_form_values(mb)
        settings = settings_store.get_all(s)
    if sending_values:
        settings.update(sending_values)
    caps = {k: values[k] for k in ("daily_cap", "hourly_cap", "min_gap_s", "max_gap_s")}
    if sending_values:
        caps.update({k: sending_values[k] for k in caps if k in sending_values})
    ctx = base_context(
        request,
        mb=values,
        mailbox_exists=mb is not None,
        has_password=bool(mb) and credentials.has_password(mb.email),
        s=settings,
        caps=caps,
        folders=settings["imap_folders_cache"],
        holidays_text="\n".join(f"{h['date']} {h['label']}" for h in settings["holidays"]),
        day_names=DAY_NAMES,
        errors=errors or {},
        flash=flash or request.query_params.get("ok"),
        cap_warning=CAP_WARNING,
    )
    return templates.TemplateResponse(request, "settings.html", ctx, status_code=status_code)


@router.get("")
def settings_page(request: Request):
    return _page(request)


def _read_mailbox_form(form) -> tuple[dict, dict]:
    errors: dict = {}
    v = {
        "display_name": forms.text(form, "display_name", errors, True, "Le nom affiché"),
        "email": forms.email(form, "email", errors, "L'adresse de la boîte"),
        "smtp_host": forms.text(form, "smtp_host", errors, True, "Le serveur SMTP"),
        "smtp_port": forms.integer(form, "smtp_port", errors, 1, 65535, "Le port SMTP"),
        "smtp_security": form.get("smtp_security", "ssl"),
        "imap_host": forms.text(form, "imap_host", errors, True, "Le serveur IMAP"),
        "imap_port": forms.integer(form, "imap_port", errors, 1, 65535, "Le port IMAP"),
        "username": forms.text(form, "username", errors, True, "L'identifiant"),
        "sent_folder": (form.get("sent_folder") or "").strip() or None,
        "watched_folders": form.getlist("watched_folders") or ["INBOX"],
        "signature": (form.get("signature") or "").replace("\r\n", "\n").rstrip(),
    }
    if v["smtp_security"] not in ("ssl", "starttls"):
        errors["smtp_security"] = "Sécurité SMTP inconnue."
    _server_guard(v, errors)
    return v, errors


SMTP_PORTS, IMAP_PORTS = {25, 465, 587, 2525}, {143, 993}


def _server_guard(v: dict, errors: dict) -> None:
    """V3 (revue externe) : sur le serveur, « Tester la connexion » et le moteur se connectent à
    l'hôte saisi. On limite aux ports mail et on refuse les adresses internes (le serveur
    lui-même, le réseau privé, le service de métadonnées du fournisseur)."""
    from app.paths import is_server_mode
    if not is_server_mode():
        return
    import ipaddress
    import socket
    for field, ports, label in (("smtp", SMTP_PORTS, "SMTP"), ("imap", IMAP_PORTS, "IMAP")):
        port, host = v.get(f"{field}_port"), (v.get(f"{field}_host") or "").strip()
        if isinstance(port, int) and port not in ports:
            errors[f"{field}_port"] = f"Port {label} non autorisé (ports possibles : {', '.join(map(str, sorted(ports)))})."
        if not host or f"{field}_host" in errors:
            continue
        try:
            addrs = {a[4][0] for a in socket.getaddrinfo(host, None)}
        except OSError:
            continue  # nom introuvable : le test de connexion le dira clairement
        for a in addrs:
            ip = ipaddress.ip_address(a.split("%")[0])
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast or ip.is_unspecified:
                errors[f"{field}_host"] = f"Serveur {label} non autorisé (adresse interne)."
                break


@router.post("/mailbox")
async def save_mailbox(request: Request):
    form = await request.form()
    values, errors = _read_mailbox_form(form)
    password = form.get("password") or ""
    with get_session() as s:
        mb = mailbox_service.get_primary(s)
        # Les plafonds sont édités dans le formulaire « Envoi » : on garde les valeurs actuelles.
        current = mailbox_service.as_form_values(mb)
        for k in ("daily_cap", "hourly_cap", "min_gap_s", "max_gap_s"):
            values[k] = current[k]
        if not password and not (mb and credentials.has_password(mb.email)):
            errors["password"] = "Le mot de passe est obligatoire."
        if errors:
            return _page(request, mailbox_values=values, errors=errors, status_code=422)
        # La session a déjà ouvert une transaction en lisant (« autobegin ») :
        # on valide avec commit(), ou on annule tout avec rollback() si keyring échoue.
        try:
            mailbox_service.save(s, values, password or None)
            s.add(EventLog(level="info", entity="mailbox", text="Réglages de la boîte mail enregistrés"))
            s.commit()
        except credentials.CredentialError as exc:
            s.rollback()
            return _page(request, mailbox_values=values, errors={"password": str(exc)}, status_code=500)
    return RedirectResponse("/settings?ok=boite", status_code=303)


def read_sending_form(form) -> tuple[dict, dict]:
    """Valide les réglages d'envoi. Partagé par la page classique et l'API V2."""
    errors: dict = {}
    days = sorted({int(d) for d in form.getlist("send_days") if d.isdigit() and 0 <= int(d) <= 6})
    if not days:
        errors["send_days"] = "Choisissez au moins un jour d'envoi."

    w1s = forms.hhmm(form, "w1_start", errors, "Début de la plage 1")
    w1e = forms.hhmm(form, "w1_end", errors, "Fin de la plage 1")
    w2s = forms.hhmm(form, "w2_start", errors, "Début de la plage 2", required=False)
    w2e = forms.hhmm(form, "w2_end", errors, "Fin de la plage 2", required=False)
    windows = [[w1s, w1e]]
    if w2s or w2e:
        windows.append([w2s, w2e])
    if not any(k.startswith("w") for k in errors):
        for start, end in windows:
            if not start or not end or forms.to_time(start) >= forms.to_time(end):
                errors["windows"] = "Chaque plage horaire doit avoir un début avant sa fin."
        if len(windows) == 2 and forms.to_time(windows[1][0]) < forms.to_time(windows[0][1]):
            errors["windows"] = "La plage 2 doit commencer après la fin de la plage 1."

    values = {
        "send_days": days,
        "send_windows": windows,
        "holidays": forms.holidays(form.get("holidays", ""), errors),
        "daily_cap": forms.integer(form, "daily_cap", errors, 1, 500, "Le plafond quotidien"),
        "hourly_cap": forms.integer(form, "hourly_cap", errors, 1, 100, "Le plafond horaire"),
        "min_gap_s": forms.integer(form, "min_gap_s", errors, 10, 3600, "Le délai minimum"),
        "max_gap_s": forms.integer(form, "max_gap_s", errors, 10, 7200, "Le délai maximum"),
        "rampup_enabled": form.get("rampup_enabled") == "on",
        "rampup_per_day": forms.integer(form, "rampup_per_day", errors, 1, 200, "La montée en charge"),
        "unsubscribe_line": forms.text(form, "unsubscribe_line", errors, True,
                                       "La ligne de désinscription"),
        "digest_time": forms.hhmm(form, "digest_time", errors, "L'heure du récapitulatif"),
        "digest_recipient": forms.email(form, "digest_recipient", errors,
                                        "Le destinataire du récapitulatif", required=False),
        "auto_reply_continues": form.get("auto_reply_continues") == "on",
    }
    if "min_gap_s" not in errors and "max_gap_s" not in errors and values["min_gap_s"] > values["max_gap_s"]:
        errors["max_gap_s"] = "Le délai maximum doit être supérieur ou égal au délai minimum."
    return values, errors


@router.post("/sending")
async def save_sending(request: Request):
    form = await request.form()
    values, errors = read_sending_form(form)

    with get_session() as s:
        mb = mailbox_service.get_primary(s)
        if mb is None:
            errors["mailbox"] = "Enregistrez d'abord la boîte mail (section du haut)."
        if errors:
            return _page(request, sending_values=values, errors=errors, status_code=422)
        for k in ("daily_cap", "hourly_cap", "min_gap_s", "max_gap_s"):
            setattr(mb, k, values.pop(k))
        for k, v in values.items():
            settings_store.set_(s, k, v)
        s.add(EventLog(level="info", entity="settings", text="Réglages d'envoi enregistrés"))
        s.commit()
    return RedirectResponse("/settings?ok=envoi", status_code=303)


@router.post("/test-mode")
async def toggle_test_mode(request: Request):
    form = await request.form()
    enabled = form.get("enabled") == "1"
    if not enabled and settings_store.test_mode_locked():
        return RedirectResponse("/settings", status_code=303)  # verrouillé pendant le développement de la V2
    with get_session() as s, s.begin():
        settings_store.set_(s, "test_mode", enabled)
        s.add(EventLog(level="warning" if not enabled else "info", entity="settings",
                       text=f"Mode test {'ACTIVÉ' if enabled else 'DÉSACTIVÉ – envois réels'}"))
    log.warning("Mode test %s", "activé" if enabled else "DÉSACTIVÉ")
    return RedirectResponse(request.headers.get("referer") or "/settings", status_code=303)


@router.post("/test-connection")
async def test_connection(request: Request):
    """Appelé par HTMX : renvoie seulement le bloc de résultat, pas toute la page.

    On teste les valeurs SAISIES dans le formulaire (même non enregistrées),
    pour pouvoir corriger un réglage avant de sauvegarder.
    """
    form = await request.form()
    values, errors = _read_mailbox_form(form)
    password = form.get("password") or ""
    with get_session() as s:
        mb = mailbox_service.get_primary(s)
        if not password and mb:
            password = credentials.get_password(mb.email) or ""
    if not password:
        errors["password"] = "Saisissez le mot de passe pour tester."
    if errors:
        return templates.TemplateResponse(
            request, "partials/connection_report.html",
            {"request": request, "errors": errors, "report": None})

    cfg = mailbox_service.server_config(values, password)
    send_email = form.get("send_test_email", "on") == "on"
    # Appel réseau bloquant (jusqu'à 30 s par serveur) dans une route async :
    # on le délègue à un thread pour ne pas figer le reste de l'app pendant le test.
    report = await run_in_threadpool(transport.check_connection, cfg, send_email)

    folder_dicts = [{"raw": f.raw_name, "display": f.display_name} for f in report.folders]
    with get_session() as s, s.begin():
        if folder_dicts:
            settings_store.set_(s, "imap_folders_cache", folder_dicts)
        s.add(EventLog(level="info" if report.ok else "warning", entity="mailbox",
                       text="Test de connexion : " + " | ".join(
                           f"{st.label} {'OK' if st.ok else 'ÉCHEC'}" for st in report.steps)))

    # Pré-sélection : dossier Envoyés détecté, et INBOX + Spam pour la surveillance.
    sent = values["sent_folder"] or report.sent_folder
    watched = set(values["watched_folders"])
    if report.junk_folder and not values["sent_folder"]:
        watched.add(report.junk_folder)
    return templates.TemplateResponse(
        request, "partials/connection_report.html",
        {"request": request, "errors": {}, "report": report, "folders": folder_dicts,
         "mb": {**values, "sent_folder": sent, "watched_folders": sorted(watched)}})

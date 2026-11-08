"""Réglages globaux (table `setting`, valeurs en JSON).

Principe : si un réglage n'a jamais été enregistré, on renvoie sa valeur par
défaut. Ainsi, le mode test est ACTIF dès la première installation sans rien
écrire en base, et ajouter un réglage plus tard ne demande aucune migration.
"""
import json
import os
from typing import Any

from sqlalchemy.orm import Session

from app.holidays import default_holidays
from app.models import Setting
from app.timeutil import to_local, utcnow

DEFAULT_UNSUBSCRIBE_LINE = (
    "Si vous ne souhaitez plus recevoir de messages de ma part, "
    "répondez simplement « STOP »."
)


UNSUBSCRIBE_DEFAULT = False  # les tests de l'ancien comportement le remettent à True


def _defaults() -> dict[str, Any]:
    return {
        "test_mode": True,
        "send_days": [0, 1, 2, 3, 4],  # lundi=0 ... vendredi=4
        "send_windows": [["09:00", "12:30"], ["14:30", "17:30"]],
        "holidays": default_holidays(to_local(utcnow()).year),
        "rampup_enabled": False,
        "rampup_per_day": 10,
        "rampup_days": 7,
        "unsubscribe_line": DEFAULT_UNSUBSCRIBE_LINE,
        # V2.12 : la ligne STOP est facultative (désactivée par défaut, choix d'Omar)
        "unsubscribe_enabled": UNSUBSCRIBE_DEFAULT,
        "starter_insurers_version": 0,
        "starter_sequences_version": 0,  # V2.15 : séquences modèles et textes fonction / secteur
        "awaiting_dismissed": {},  # V2.13 : « À répondre » rangés à la main {expéditeur: date ISO du dernier rangé}  # V2.12 : version de la liste d'assureurs de départ déjà appliquée
        "digest_time": "18:00",
        "digest_recipient": "",  # vide = adresse de la boîte mail
        "auto_reply_continues": True,
        "followup_days": 3,  # V2.7 : « sans réponse depuis N jours ouvrés » (tableau de bord, boîte mail)
        "quote_followup_days": 4,  # Dossiers de cotation : relancer une compagnie consultée après N jours ouvrés
        "notifications_seen": [],  # V2.8 : clés des notifications déjà vues (pastille de la cloche)
        "guide_checked": [],
        "guide_done": [],  # V2.22 : étapes de « Bien démarrer » déjà atteintes une fois (restent cochées)
        "backup_copy_dir": "",  # V2.20 : second dossier où copier chaque sauvegarde (vide = aucun)
        "update_url": "",  # V2.17 : lien de partage du kit (vide = lien intégré à l'application)
        "update_status": {},  # V2.17 : dernière vérification {checked_at, available, error}  # V2.16 : étapes de « Bien démarrer » cochées à la main
        "imap_folders_cache": [],  # dernière liste de dossiers vue lors d'un test de connexion
        "custom_field_labels": {},  # clé -> libellé d'origine (« accroche_suggeree » -> « Accroche suggérée »)
        "engine_next_allowed_at": None,  # ISO UTC : pas d'envoi avant (délai aléatoire entre 2 envois)
        "engine_last_tick": None,        # ISO UTC : dernière exécution du moteur
        "engine_last_error": "",         # erreur globale (ex. mot de passe refusé) affichée au tableau de bord
        "last_imap_sync": None,          # ISO UTC : dernière synchronisation IMAP réussie
        "last_imap_attempt": None,       # ISO UTC : dernière tentative (réussie ou non)
        "imap_last_error": "",           # erreur de la dernière synchronisation
        "digest_last_date": None,        # date locale du dernier récapitulatif envoyé
        "seed_done": False,  # contenu de départ déjà créé ? (§7)
    }


def test_mode_locked() -> bool:
    """V2 en développement : start.bat définit ODDO_FORCE_TEST_MODE=1. Le mode test est alors
    imposé quoi qu'indique la base, pour qu'aucun email réel ne parte en double avec la V1."""
    return os.environ.get("ODDO_FORCE_TEST_MODE") == "1"


# V3 : réglages communs à toute l'équipe ; tous les autres sont propres à chaque employé
# (mode test, plages d'envoi, ligne STOP, récapitulatif, cloche, guide…).
GLOBAL_KEYS = frozenset({
    "holidays", "starter_insurers_version", "starter_sequences_version", "seed_done",
    "backup_copy_dir", "update_url", "update_status", "custom_field_labels", "engine_last_tick",
    "quote_followup_days",  # Dossiers de cotation : réglage du cabinet (pas d'un employé)
})


def _key(key: str) -> str:
    """Nom en base : « u3:test_mode » pour l'employé n°3 ; inchangé en poste unique."""
    from app.current import user_id
    uid = user_id()
    return key if uid is None or key in GLOBAL_KEYS else f"u{uid}:{key}"


def _cache(session: Session) -> dict[str, str]:
    """V3 : tous les réglages utiles (communs + ceux de l'employé) lus en UNE requête par
    session, au lieu d'une par réglage : sur le serveur, la base est à distance."""
    from app.current import user_id
    ck = ("oddo_settings", user_id())
    cached = session.info.get(ck)
    if cached is None:
        from sqlalchemy import select
        uid = user_id()
        stmt = select(Setting.key, Setting.value)
        if uid is not None:
            from sqlalchemy import or_
            stmt = stmt.where(or_(Setting.key.in_(GLOBAL_KEYS), Setting.key.like(f"u{uid}:%")))
        cached = dict(session.execute(stmt).all())
        session.info[ck] = cached
    return cached


def get(session: Session, key: str) -> Any:
    if key == "test_mode" and test_mode_locked():
        return True
    raw = _cache(session).get(_key(key))
    if raw is None:
        defaults = _defaults()
        if key not in defaults:
            raise KeyError(f"Réglage inconnu : {key}")
        return defaults[key]
    return json.loads(raw)


def set_(session: Session, key: str, value: Any) -> None:
    if key not in _defaults():
        raise KeyError(f"Réglage inconnu : {key}")
    row = session.get(Setting, _key(key))
    encoded = json.dumps(value, ensure_ascii=False)
    if row is None:
        session.add(Setting(key=_key(key), value=encoded))
    else:
        row.value = encoded
    _cache(session)[_key(key)] = encoded


def get_all(session: Session) -> dict[str, Any]:
    return {k: get(session, k) for k in _defaults()}

"""Petits validateurs de formulaire.

Chaque fonction lit un champ, le convertit, et ajoute un message en français
dans `errors` si la valeur est invalide. On affiche ensuite TOUTES les erreurs
d'un coup, plutôt que la première seulement.
"""
import re
from datetime import date, time

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
HHMM_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


def text(form, name: str, errors: dict, required: bool = False, label: str = "") -> str:
    value = (form.get(name) or "").strip()
    if required and not value:
        errors[name] = f"{label or name} est obligatoire."
    return value


def email(form, name: str, errors: dict, label: str = "L'adresse", required: bool = True) -> str:
    value = (form.get(name) or "").strip().lower()
    if not value and not required:
        return ""
    if not EMAIL_RE.match(value):
        errors[name] = f"{label} n'est pas une adresse email valide."
    return value


def integer(form, name: str, errors: dict, lo: int, hi: int, label: str = "") -> int:
    raw = (form.get(name) or "").strip()
    try:
        value = int(raw)
    except ValueError:
        errors[name] = f"{label or name} doit être un nombre entier."
        return lo
    if not lo <= value <= hi:
        errors[name] = f"{label or name} doit être compris entre {lo} et {hi}."
    return value


def hhmm(form, name: str, errors: dict, label: str = "", required: bool = True) -> str:
    value = (form.get(name) or "").strip()
    if not value and not required:
        return ""
    if not HHMM_RE.match(value):
        errors[name] = f"{label or name} doit être au format HH:MM (ex. 09:00)."
    return value


def to_time(value: str) -> time:
    h, m = value.split(":")
    return time(int(h), int(m))


def holidays(raw: str, errors: dict, name: str = "holidays") -> list[dict]:
    """Une ligne par jour férié : « AAAA-MM-JJ Libellé »."""
    out, bad = [], []
    for n, line in enumerate(raw.splitlines(), start=1):
        line = line.strip()
        if not line:
            continue
        iso, _, label = line.partition(" ")
        try:
            date.fromisoformat(iso)
        except ValueError:
            bad.append(str(n))
            continue
        out.append({"date": iso, "label": label.strip()})
    if bad:
        errors[name] = f"Date illisible ligne(s) {', '.join(bad)} : utilisez AAAA-MM-JJ."
    out.sort(key=lambda h: h["date"])
    return out

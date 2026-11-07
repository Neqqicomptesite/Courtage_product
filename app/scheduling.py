"""Calcul des dates d'envoi (§4, §6.4, §6.6).

Toutes les fonctions reçoivent et renvoient des dates UTC « aware ». Les
calculs de jours et d'heures se font en heure du Maroc (Africa/Casablanca),
puis on reconvertit en UTC. Ainsi un envoi « à 09:00 » reste à 09:00 heure
locale, même quand le Maroc change d'heure (Ramadan, etc.).

Deux notions à ne pas confondre :
- jour OUVRÉ (pour compter les délais J+3…) : lundi-vendredi, hors jours fériés ;
- jour d'ENVOI (pour la fenêtre) : les jours cochés dans les Réglages, hors fériés.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from sqlalchemy.orm import Session

from app import settings_store
from app.timeutil import TZ, to_local


@dataclass(frozen=True)
class SendWindow:
    days: frozenset[int]                    # 0 = lundi
    ranges: tuple[tuple[time, time], ...]   # plages horaires locales, triées
    holidays: frozenset[date]

    @classmethod
    def from_settings(cls, session: Session) -> "SendWindow":
        def t(s: str) -> time:
            h, m = s.split(":")
            return time(int(h), int(m))
        ranges = tuple(sorted((t(a), t(b)) for a, b in settings_store.get(session, "send_windows")))
        hol = frozenset(date.fromisoformat(h["date"]) for h in settings_store.get(session, "holidays"))
        return cls(frozenset(settings_store.get(session, "send_days")), ranges, hol)

    # ------------------------------------------------------------------ jours
    def is_business_day(self, d: date) -> bool:
        return d.weekday() < 5 and d not in self.holidays

    def is_send_day(self, d: date) -> bool:
        return d.weekday() in self.days and d not in self.holidays

    def add_days(self, d: date, n: int, business: bool) -> date:
        """Ajoute n jours (ouvrés ou calendaires) à une date locale."""
        if not business:
            return d + timedelta(days=n)
        while n > 0:
            d += timedelta(days=1)
            if self.is_business_day(d):
                n -= 1
        return d

    # ---------------------------------------------------------------- horaires
    def _local(self, d: date, t: time) -> datetime:
        return datetime.combine(d, t, tzinfo=TZ)

    def is_open(self, when_utc: datetime) -> bool:
        local = to_local(when_utc)
        if not self.is_send_day(local.date()):
            return False
        return any(a <= local.time() < b for a, b in self.ranges)

    def next_open(self, after_utc: datetime) -> datetime:
        """Premier instant >= after_utc où l'envoi est autorisé (en UTC)."""
        local = to_local(after_utc)
        d = local.date()
        for _ in range(400):  # garde-fou : jamais de boucle infinie si les réglages sont absurdes
            if self.is_send_day(d):
                for a, b in self.ranges:
                    start, end = self._local(d, a), self._local(d, b)
                    if local < end:
                        return max(local, start).astimezone(after_utc.tzinfo)
            d += timedelta(days=1)
            local = self._local(d, time(0, 0))
        raise ValueError("Aucun créneau d'envoi dans l'année : vérifiez les jours et plages d'envoi.")

    def due_after(self, previous_sent_utc: datetime, delay_days: int, business: bool,
                  weekday: int | None = None, at: time | None = None) -> datetime:
        """Échéance d'une étape : `delay_days` jours après l'envoi précédent, à la
        première ouverture de la fenêtre ce jour-là (ou après).

        V2.5, « relance à un jour précis » : avec `weekday` (0 = lundi), on attend ensuite ce
        jour de la semaine ; avec `at`, l'heure locale voulue (ramenée dans les plages d'envoi).
        Ex. J+3 puis mardi 10:00 : au moins 3 jours après, le premier mardi suivant, à 10:00.
        Un férié ou un jour sans envoi repousse à la prochaine ouverture."""
        local_prev = to_local(previous_sent_utc)
        target = self.add_days(local_prev.date(), delay_days, business)
        if weekday is None and at is None:
            if delay_days == 0:
                return self.next_open(previous_sent_utc)
            return self.next_open(self._local(target, time(0, 0)).astimezone(previous_sent_utc.tzinfo))
        if weekday is not None:
            while target.weekday() != weekday:
                target += timedelta(days=1)
        if at is not None:
            when = self._local(target, at)
            while when <= local_prev:  # l'heure est déjà passée ce jour-là
                when += timedelta(days=7 if weekday is not None else 1)
            return self.next_open(when.astimezone(previous_sent_utc.tzinfo))
        start = max(self._local(target, time(0, 0)), local_prev)
        return self.next_open(start.astimezone(previous_sent_utc.tzinfo))

    def step_due(self, previous_utc: datetime, step) -> datetime:
        """Échéance d'une étape de séquence (délai, jour précis et heure éventuels)."""
        return self.due_after(previous_utc, step.delay_days, step.business_days,
                              getattr(step, "weekday", None), parse_hhmm(getattr(step, "send_time", None)))


def parse_hhmm(value: str | None) -> time | None:
    if not value:
        return None
    h, m = value.split(":")
    return time(int(h), int(m))


def planned_dates(window: SendWindow, start_utc: datetime, steps) -> list[datetime]:
    """Dates prévues de chaque étape, SANS tenir compte des plafonds (estimation d'aperçu)."""
    out: list[datetime] = []
    prev = start_utc
    for st in steps:
        due = window.step_due(prev, st)
        out.append(due)
        prev = due
    return out

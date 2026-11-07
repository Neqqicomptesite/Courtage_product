"""Jours fériés marocains préremplis (modifiables dans Réglages).

Sources consultées le 03/11/2026 (à revérifier chaque année) :
- calendrier 2026-2027 publié par wafir.ma ;
- annonce de la Fête de l'Unité (31 octobre), décrétée en 2025.
Les fêtes religieuses dépendent de l'observation du croissant de lune : les
dates 2027 sont des ESTIMATIONS, marquées « (estimé) », à corriger dès
l'annonce officielle.
"""

# (date ISO, libellé). Le texte « (estimé) » signale une date lunaire non confirmée.
MOROCCO_HOLIDAYS: dict[int, list[tuple[str, str]]] = {
    2026: [
        ("2026-01-01", "Nouvel an"),
        ("2026-01-11", "Manifeste de l'indépendance"),
        ("2026-01-14", "Nouvel an amazigh (Yennayer)"),
        ("2026-03-20", "Aïd al-Fitr"),
        ("2026-03-21", "Aïd al-Fitr (2e jour)"),
        ("2026-05-01", "Fête du Travail"),
        ("2026-05-27", "Aïd al-Adha"),
        ("2026-05-28", "Aïd al-Adha (2e jour)"),
        ("2026-06-17", "1er Moharram"),
        ("2026-07-30", "Fête du Trône"),
        ("2026-08-14", "Allégeance Oued Eddahab"),
        ("2026-08-20", "Révolution du Roi et du Peuple"),
        ("2026-08-21", "Fête de la Jeunesse"),
        ("2026-08-25", "Aïd al-Mawlid"),
        ("2026-08-26", "Aïd al-Mawlid (2e jour)"),
        ("2026-10-31", "Fête de l'Unité"),
        ("2026-11-06", "Marche Verte"),
        ("2026-11-18", "Fête de l'Indépendance"),
    ],
    2027: [
        ("2027-01-01", "Nouvel an"),
        ("2027-01-11", "Manifeste de l'indépendance"),
        ("2027-01-14", "Nouvel an amazigh (Yennayer)"),
        ("2027-03-10", "Aïd al-Fitr (estimé)"),
        ("2027-03-11", "Aïd al-Fitr, 2e jour (estimé)"),
        ("2027-05-01", "Fête du Travail"),
        ("2027-05-17", "Aïd al-Adha (estimé)"),
        ("2027-05-18", "Aïd al-Adha, 2e jour (estimé)"),
        ("2027-06-06", "1er Moharram (estimé)"),
        ("2027-07-30", "Fête du Trône"),
        ("2027-08-14", "Allégeance Oued Eddahab"),
        ("2027-08-14", "Aïd al-Mawlid (estimé)"),
        ("2027-08-15", "Aïd al-Mawlid, 2e jour (estimé)"),
        ("2027-08-20", "Révolution du Roi et du Peuple"),
        ("2027-08-21", "Fête de la Jeunesse"),
        ("2027-10-31", "Fête de l'Unité"),
        ("2027-11-06", "Marche Verte"),
        ("2027-11-18", "Fête de l'Indépendance"),
    ],
}


def default_holidays(year: int) -> list[dict]:
    """Année en cours + année suivante (une campagne lancée en novembre déborde sur janvier)."""
    out = []
    for y in (year, year + 1):
        for iso, label in MOROCCO_HOLIDAYS.get(y, []):
            out.append({"date": iso, "label": label})
    return out

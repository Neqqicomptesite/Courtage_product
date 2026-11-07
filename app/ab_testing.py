"""Répartition A/B des objets de l'étape 1 (§6.4).

Exigences : 50/50, au hasard, et STABLE (un contact garde sa variante).
- Au hasard : on mélange les contacts avant de les répartir.
- 50/50 exact : on alterne A, B, A, B… sur la liste mélangée (un tirage à pile ou
  face donnerait par exemple 58/42 sur 100 contacts, ce qui fausse la comparaison).
- Stable : la variante est enregistrée une fois pour toutes dans l'inscription ;
  ajouter des contacts plus tard les place dans le groupe le moins rempli, sans
  toucher aux variantes déjà attribuées.
"""
from __future__ import annotations

import random


def assign_variants(new_ids: list[int], labels: list[str], existing: dict[str, int] | None = None,
                    rng: random.Random | None = None) -> dict[int, str]:
    """Renvoie {contact_id: label} pour les NOUVEAUX contacts uniquement.

    `existing` : nombre de contacts déjà dans chaque groupe, pour rééquilibrer.
    """
    if not labels:
        return {}
    if len(labels) == 1:
        return {cid: labels[0] for cid in new_ids}
    rng = rng or random.SystemRandom()
    counts = {lab: (existing or {}).get(lab, 0) for lab in labels}
    ids = list(new_ids)
    rng.shuffle(ids)
    out = {}
    for cid in ids:
        # le groupe le moins rempli ; en cas d'égalité, ordre alphabétique (A avant B)
        lab = min(labels, key=lambda x: (counts[x], x))
        out[cid] = lab
        counts[lab] += 1
    return out

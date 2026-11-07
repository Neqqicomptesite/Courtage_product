"""Contenu de départ (cahier des charges §7).

Créé une seule fois (drapeau `seed_done`) : si Omar supprime ou modifie un
bloc ensuite, on ne le recrée pas dans son dos au redémarrage suivant.
"""
from sqlalchemy.orm import Session

from app import settings_store
from app.models import ContentBlock, Sequence, Step, StepVariant

TARGET_BLOCKS = {
    "FIN": "Finance et administration",
    "RH": "Ressources humaines",
    "DIR": "Dirigeant",
}
SECTOR_BLOCKS = {
    "IND": "Industrie et énergie",
    "SRV": "Services, IT et conseil",
    "BTP": "BTP et immobilier",
    "COM": "Commerce et distribution",
    "TRA": "Transport et logistique",
    "AGRO": "Agroalimentaire",
    "SANTE": "Santé",
}

STEP1_BODY = """Bonjour {{ prenom | "Madame, Monsieur" }},

{{ bloc_cible }}

{{ bloc_secteur }}

Seriez-vous disponible pour un échange de 15 minutes la semaine prochaine ?"""

STEP2_BODY = """Bonjour {{ prenom | "Madame, Monsieur" }},

Je me permets de revenir vers vous au sujet de mon message ci-dessous. À RÉDIGER : relance courte, un seul argument."""

STEP3_BODY = """Bonjour {{ prenom | "Madame, Monsieur" }},

Dernier message de ma part sur ce sujet. À RÉDIGER : relance finale, porte ouverte."""


def run_seed(session: Session) -> bool:
    """Renvoie True si le contenu a été créé, False s'il existait déjà."""
    if settings_store.get(session, "seed_done"):
        return False

    for key, label in TARGET_BLOCKS.items():
        session.add(ContentBlock(kind="target", key=key,
                                 body=f"À RÉDIGER – trame « {label} » ({key})."))
    for key, label in SECTOR_BLOCKS.items():
        session.add(ContentBlock(kind="sector", key=key,
                                 body=f"À RÉDIGER – paragraphe secteur « {label} » ({key})."))

    seq = Sequence(name="Prospection PME – 3 étapes")
    session.add(seq)
    session.flush()  # pour obtenir seq.id avant de créer les étapes

    s1 = Step(sequence_id=seq.id, position=1, delay_days=0, business_days=True,
              same_thread=False, body_template=STEP1_BODY)
    s2 = Step(sequence_id=seq.id, position=2, delay_days=3, business_days=True,
              same_thread=True, body_template=STEP2_BODY)
    # « J+7 » = 7 jours ouvrés après l'étape 1, donc 4 jours après l'étape 2
    # (le délai est stocké depuis l'étape précédente, voir DECISIONS.md).
    s3 = Step(sequence_id=seq.id, position=3, delay_days=4, business_days=True,
              same_thread=True, body_template=STEP3_BODY)
    session.add_all([s1, s2, s3])
    session.flush()
    session.add_all([
        StepVariant(step_id=s1.id, label="A", subject_template="{{ entreprise }} : vos contrats d'assurance"),
        StepVariant(step_id=s1.id, label="B", subject_template="Question rapide sur vos assurances"),
    ])

    settings_store.set_(session, "seed_done", True)
    return True

# Cotalis (nom de travail)

Logiciel en ligne pour les **cabinets de courtage et intermédiaires en assurance** : prospection par
email, suivi des réponses, contacts et compagnies partagés, et à venir le suivi des dossiers de
cotation, des contrats et des échéances.

Le produit part du code d'**ODDO Séquences V3**, l'outil interne d'ODDO Assurances, qui reste un
projet séparé (dépôt `Neqqicomptesite/oddo-sequences`) et n'est pas modifié par ce dépôt.

> Le nom « Cotalis » est provisoire. Il est affiché partout à partir d'une seule valeur :
> `APP_NAME` dans `app/__init__.py`, remplaçable sans toucher au code par la variable
> d'environnement `PRODUCT_NAME`. Le navigateur le reçoit via `/api/auth/config`.
> Vérifier la disponibilité de la marque (OMPIC au Maroc, INPI / EUIPO si besoin) avant un lancement.

## Où on en est

| Phase | Contenu | État |
|---|---|---|
| 0 | Dépôt séparé, nom et marque réglables, logo neutre, tests automatiques | fait |
| 1 | Plusieurs cabinets sur une même installation (`org_id`), inscription, réglages et marque par cabinet, tests d'étanchéité entre cabinets | à faire |
| 2 | Dossier de cotation (A1 à A3) | à faire |
| 3 | Tableau comparatif semi-manuel (A4) | à faire |
| 4 | Contrats et échéances (B1, B2) | à faire |
| 5 | Tableau de bord du gérant (E1) | à faire |
| 6 | Boîte mail partagée (C2) | à faire |
| 7 | Connexion Gmail / Microsoft 365 (F1) | à faire |

D1, D2 et les fonctions d'IA sont repoussées. Chaque phase commence par une courte spécification à
valider. Le détail des choix est dans `DECISIONS.md`.

## Architecture (héritée de la V3)

- **Serveur** : FastAPI + SQLAlchemy 2 + Alembic, un seul processus avec le moteur d'envoi
  (APScheduler). PostgreSQL (Supabase) en production, SQLite pour le poste unique et les tests.
- **Interface** : React 18 / TypeScript / Vite / Tailwind dans `frontend/`, compilée dans
  `app/static/v2` (le résultat compilé est versionné : le serveur n'a pas besoin de Node).
- **Connexion** : Supabase Auth (jetons vérifiés par JWKS), sur invitation.
- **Cloisonnement par employé** : filtre global SQLAlchemy (`app/scope.py`), réglages préfixés
  par employé (`app/settings_store.py`), coffre chiffré pour les mots de passe des boîtes mail.
- **Déploiement** : `deploy/` (cloud-init → `install.sh`, `update.sh` la nuit depuis la branche
  `production`, `backup.sh` chiffré hors serveur, `set-domain.sh`).

## Développer

```bash
python3.12 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest -q                               # SQLite
TEST_DATABASE_URL=postgresql://postgres@127.0.0.1:5432/app_test .venv/bin/python -m pytest -q   # PostgreSQL

cd frontend && npm ci && npm run build                      # recompile app/static/v2
```

Les tests tournent aussi sur GitHub à chaque envoi (`.github/workflows/tests.yml`), sur SQLite et
PostgreSQL.

## Reste de la V3 à reprendre plus tard

- Les données de départ (assureurs, séquences types) sont encore celles d'ODDO : gardées pour
  l'instant, à remplacer par un jeu neutre avant d'ouvrir à d'autres cabinets.
- Les captures du guide (`frontend/public/guide`) montrent encore l'ancienne marque : à refaire
  avec des données fictives quand l'interface sera stabilisée.
- Les chemins techniques du serveur (`/etc/oddo`, `/opt/oddo`, utilisateur `oddo`, variables
  `ODDO_*`) gardent leur nom : les renommer en même temps que la mise en place du serveur de test.
- Le guide d'utilisation du poste unique (V2) est archivé dans `docs/guide-poste-unique-v2.md`.

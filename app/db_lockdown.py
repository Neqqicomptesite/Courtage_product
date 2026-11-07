"""V3 : la base Supabase n'est utilisée QUE par le serveur de l'appli (connexion PostgreSQL directe).

Supabase expose aussi les tables du schéma « public » sur son API web (PostgREST), avec la
clé « publishable », publique par nature. Pour des tables créées en SQL (comme ici), les rôles
`anon` et `authenticated` reçoivent par défaut les droits de lecture/écriture : sans
protection, n'importe qui aurait pu lire les contacts et les emails, ou se créer administrateur.

Protection en deux couches, appliquée à chaque démarrage (sans effet si déjà en place) :
1. RLS activée sur chaque table, sans aucune règle : tout est refusé à `anon` et
   `authenticated`. Le serveur se connecte avec le propriétaire des tables, que la RLS
   n'arrête pas ;
2. droits retirés à `anon` et `authenticated` sur les tables existantes et futures.
Sans effet hors PostgreSQL ; les rôles absents (PostgreSQL local des tests) sont ignorés.
"""
from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.engine import Connection

API_ROLES = ("anon", "authenticated")


def lock_down(conn: Connection) -> list[str]:
    if conn.dialect.name != "postgresql":
        return []
    tables = [r[0] for r in conn.execute(text(
        "SELECT tablename FROM pg_tables WHERE schemaname = 'public'"))]
    for t in tables:
        conn.execute(text(f'ALTER TABLE public."{t}" ENABLE ROW LEVEL SECURITY'))
    roles = [r[0] for r in conn.execute(text("SELECT rolname FROM pg_roles WHERE rolname = ANY(:r)"),
                                        {"r": list(API_ROLES)})]
    if roles:
        who = ", ".join(roles)
        conn.execute(text(f"REVOKE ALL ON ALL TABLES IN SCHEMA public FROM {who}"))
        conn.execute(text(f"REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM {who}"))
        conn.execute(text(f"ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON TABLES FROM {who}"))
        conn.execute(text(f"ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON SEQUENCES FROM {who}"))
    return tables

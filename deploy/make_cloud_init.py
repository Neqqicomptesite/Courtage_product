"""Fabrique le fichier « cloud-config » à coller dans Hetzner (création du serveur).

    python deploy/make_cloud_init.py chemin/vers/secrets-v3.txt  > cloud-config.yaml

Lit les secrets (URL, PUBLISHABLE, SECRET, DB, SECRET_KEY, ADMIN_EMAIL, GITHUB_TOKEN, et
facultatifs ADMIN_NAME, HOST) et n'affiche RIEN d'autre que le fichier produit.
Le fichier contient des secrets : ne pas l'envoyer par mail ni le partager.
"""
import sys

REQUIRED = ("URL", "PUBLISHABLE", "SECRET", "DB", "SECRET_KEY", "ADMIN_EMAIL", "GITHUB_TOKEN")


def read(path: str) -> dict:
    out = {}
    for line in open(path, encoding="utf-8-sig").read().splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            k, v = line.split("=", 1)
            out[k.strip().upper()] = v.strip()
    return out


def main() -> int:
    s = read(sys.argv[1])
    missing = [k for k in REQUIRED if not s.get(k)]
    if missing:
        print("Lignes manquantes dans le fichier de secrets : " + ", ".join(missing), file=sys.stderr)
        return 1
    if "[" in s["DB"] or "YOUR-PASSWORD" in s["DB"]:
        print("La ligne DB contient encore un emplacement à remplacer.", file=sys.stderr)
        return 1
    env = {
        "DATABASE_URL": s["DB"],
        "SUPABASE_URL": s["URL"].rstrip("/"),
        "SUPABASE_PUBLISHABLE_KEY": s["PUBLISHABLE"],
        "SUPABASE_SECRET_KEY": s["SECRET"],
        "ODDO_SECRET_KEY": s["SECRET_KEY"],
        "ODDO_ADMIN_EMAIL": s["ADMIN_EMAIL"],
        "ODDO_ADMIN_NAME": s.get("ADMIN_NAME", ""),
        "ODDO_HOST": s.get("HOST", ""),
        "GITHUB_TOKEN": s["GITHUB_TOKEN"],
    }
    for k, v in env.items():
        if any(c in v for c in "\n\r'\""):
            print(f"Valeur inattendue pour {k} (guillemet ou retour à la ligne).", file=sys.stderr)
            return 1
    body = "\n".join(f"      {k}='{v}'" for k, v in env.items())
    print(f"""#cloud-config
# ODDO Séquences : configuration du serveur. CONTIENT DES SECRETS : ne pas partager.
package_update: true
package_upgrade: true
ssh_pwauth: false
timezone: Africa/Casablanca
write_files:
  - path: /etc/oddo/env
    permissions: '0600'
    content: |
{body}
runcmd:
  - [bash, -c, "set -a; . /etc/oddo/env; git clone --depth 20 -b production https://x-access-token:$GITHUB_TOKEN@github.com/Neqqicomptesite/oddo-sequences.git /opt/oddo && bash /opt/oddo/deploy/install.sh"]
""")
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env bash
# ODDO Séquences V3 : installation / mise à niveau du serveur (Ubuntu 24.04).
# Lancé une fois par cloud-init à la création du serveur, relançable sans risque.
# Les secrets sont dans /etc/oddo/env (écrit par cloud-init, lisible par root et oddo seulement).
set -euo pipefail
exec > >(tee -a /var/log/oddo-install.log) 2>&1
echo "=== install $(date -Is) ==="

REPO="Neqqicomptesite/oddo-sequences"
BRANCH=production
APP=/opt/oddo
DATA=/var/lib/oddo
ENVF=/etc/oddo/env
export DEBIAN_FRONTEND=noninteractive

[ -f "$ENVF" ] || { echo "Fichier $ENVF manquant"; exit 1; }
set -a; . "$ENVF"; set +a

# 1. Paquets : Python, git, Caddy (HTTPS automatique), client PostgreSQL récent (sauvegardes)
apt-get update -q
apt-get install -y -q python3-venv python3-dev git caddy ufw curl ca-certificates postgresql-common
if ! command -v pg_dump >/dev/null || [ "$(pg_dump --version | grep -oE '[0-9]+' | head -1)" -lt 17 ]; then
  if /usr/share/postgresql-common/pgdg/apt.postgresql.org.sh -y && apt-get install -y -q postgresql-client-18; then :
  else echo "ATTENTION : client PostgreSQL 18 non installé, sauvegardes à vérifier"; apt-get install -y -q postgresql-client; fi
fi

# 2. Pare-feu : SSH, HTTP (certificat), HTTPS
ufw allow 22/tcp; ufw allow 80/tcp; ufw allow 443/tcp; ufw --force enable

# 3. Utilisateur système et dossiers
id oddo >/dev/null 2>&1 || useradd --system --home "$DATA" --shell /usr/sbin/nologin oddo
install -d -o oddo -g oddo -m 750 "$DATA" /var/backups/oddo
chown root:oddo "$ENVF"; chmod 640 "$ENVF"

# 4. Adresse publique : nom fourni (ODDO_HOST) ou, à défaut, <ip>.sslip.io (certificat gratuit)
if [ -z "${ODDO_HOST:-}" ]; then
  IP=$(curl -fsS http://169.254.169.254/hetzner/v1/metadata/public-ipv4 || curl -fsS https://api.ipify.org)
  ODDO_HOST="${IP//./-}.sslip.io"
fi
cat > /etc/oddo/host.env <<HOST
ODDO_HOST=$ODDO_HOST
ODDO_PUBLIC_HOSTS=$ODDO_HOST
ODDO_PUBLIC_URL=https://$ODDO_HOST
HOST
chown root:oddo /etc/oddo/host.env; chmod 640 /etc/oddo/host.env
echo "Adresse : https://$ODDO_HOST"

# 5. Code (dépôt privé, clé GitHub en lecture seule)
git config --system --get-all safe.directory | grep -qx "$APP" || git config --system --add safe.directory "$APP"
if [ ! -d "$APP/.git" ]; then
  git clone --depth 20 -b "$BRANCH" "https://x-access-token:${GITHUB_TOKEN}@github.com/${REPO}.git" "$APP"
else
  git -C "$APP" remote set-url origin "https://x-access-token:${GITHUB_TOKEN}@github.com/${REPO}.git"
  git -C "$APP" fetch --depth 20 origin "+refs/heads/$BRANCH:refs/remotes/origin/$BRANCH" && git -C "$APP" checkout -B "$BRANCH" origin/"$BRANCH"
fi
chmod 700 "$APP/.git"
[ -d "$APP/.venv" ] || python3 -m venv "$APP/.venv"
"$APP/.venv/bin/pip" install -q --upgrade pip
"$APP/.venv/bin/pip" install -q -r "$APP/requirements.txt"
chown -R oddo:oddo "$APP"

# 6. Services : appli, mises à jour automatiques, sauvegarde de nuit, HTTPS
install -m 644 "$APP"/deploy/systemd/*.service "$APP"/deploy/systemd/*.timer /etc/systemd/system/
install -m 755 "$APP/deploy/update.sh" "$APP/deploy/backup.sh" /usr/local/sbin/
cat > /etc/caddy/Caddyfile <<CADDY
$ODDO_HOST {
	encode gzip
	reverse_proxy 127.0.0.1:8765
	header Strict-Transport-Security "max-age=31536000"
}
CADDY
systemctl daemon-reload
systemctl enable --now oddo.service oddo-update.timer oddo-backup.timer
systemctl restart caddy
echo "=== install terminée $(date -Is) ==="

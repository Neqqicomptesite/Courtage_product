#!/usr/bin/env bash
# Donner une vraie adresse à l'appli (ex. sequences.oddo.ma), à lancer en root :
#   bash /opt/oddo/deploy/set-domain.sh sequences.oddo.ma
# Prérequis : chez l'hébergeur du domaine, un enregistrement DNS « A » qui pointe vers l'IP
# du serveur. Le script vérifie ce point, enregistre l'adresse, obtient le certificat HTTPS
# (Caddy, automatique), et garde l'ancienne adresse sslip.io en redirection vers la nouvelle.
set -euo pipefail
NEW="$(echo "${1:-}" | tr 'A-Z' 'a-z')"
[[ "$NEW" =~ ^[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)+$ ]] || {
  echo "Usage : bash /opt/oddo/deploy/set-domain.sh sequences.oddo.ma"; exit 1; }
IP=$(curl -fsS http://169.254.169.254/hetzner/v1/metadata/public-ipv4 || curl -fsS https://api.ipify.org)
OLD="${IP//./-}.sslip.io"
GOT=$(getent ahostsv4 "$NEW" | awk '{print $1; exit}' || true)
if [ "$GOT" != "$IP" ]; then
  echo "Le nom $NEW ne pointe pas encore vers ce serveur ($IP) : il pointe vers « ${GOT:-rien} »."
  echo "Vérifiez l'enregistrement A chez l'hébergeur du domaine, attendez quelques minutes, puis relancez."
  exit 1
fi
if grep -q '^ODDO_HOST=' /etc/oddo/env; then
  sed -i "s|^ODDO_HOST=.*|ODDO_HOST='$NEW'|" /etc/oddo/env
else
  echo "ODDO_HOST='$NEW'" >> /etc/oddo/env
fi
cat > /etc/oddo/host.env <<HOST
ODDO_HOST=$NEW
ODDO_PUBLIC_HOSTS=$NEW,$OLD
ODDO_PUBLIC_URL=https://$NEW
HOST
chown root:oddo /etc/oddo/host.env; chmod 640 /etc/oddo/host.env
cat > /etc/caddy/Caddyfile <<CADDY
$NEW {
	encode gzip
	reverse_proxy 127.0.0.1:8765
	header Strict-Transport-Security "max-age=31536000"
}
$OLD {
	redir https://$NEW{uri} permanent
}
CADDY
systemctl restart caddy
systemctl restart oddo.service
echo "OK : l'appli répond sur https://$NEW (l'ancienne adresse y renvoie)."
echo "Le certificat HTTPS peut prendre une minute à arriver."

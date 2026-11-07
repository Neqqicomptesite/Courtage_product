#!/usr/bin/env bash
# Mise à jour automatique : si GitHub a une nouvelle version, on la récupère et on redémarre.
set -euo pipefail
APP=/opt/oddo
cd "$APP"
G="sudo -u oddo git"
$G fetch -q --depth 20 origin main
if [ "$($G rev-parse HEAD)" = "$($G rev-parse origin/main)" ]; then exit 0; fi
echo "Mise à jour $($G rev-parse --short HEAD) -> $($G rev-parse --short origin/main)"
$G reset -q --hard origin/main
sudo -u oddo "$APP/.venv/bin/pip" install -q -r requirements.txt
# fichiers système livrés avec le code (services, scripts)
install -m 644 deploy/systemd/*.service deploy/systemd/*.timer /etc/systemd/system/
install -m 755 deploy/update.sh deploy/backup.sh /usr/local/sbin/
systemctl daemon-reload
systemctl restart oddo.service

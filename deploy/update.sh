#!/usr/bin/env bash
# Mise à jour automatique : si GitHub a une nouvelle version, on la récupère et on redémarre.
set -euo pipefail
APP=/opt/oddo
# Branche « production » : le code n'arrive sur le serveur que lorsqu'il y est poussé
# (après tests), pas à chaque modification de la branche de travail « main ».
BRANCH=production
cd "$APP"
G="sudo -u oddo git"
$G fetch -q --depth 20 origin "+refs/heads/$BRANCH:refs/remotes/origin/$BRANCH"
if [ "$($G rev-parse HEAD)" = "$($G rev-parse origin/"$BRANCH")" ]; then exit 0; fi
echo "Mise à jour $($G rev-parse --short HEAD) -> $($G rev-parse --short origin/"$BRANCH")"
$G reset -q --hard origin/"$BRANCH"
sudo -u oddo "$APP/.venv/bin/pip" install -q -r requirements.txt
# fichiers système livrés avec le code (services, scripts)
install -m 644 deploy/systemd/*.service deploy/systemd/*.timer /etc/systemd/system/
install -m 755 deploy/update.sh deploy/backup.sh /usr/local/sbin/
systemctl daemon-reload
systemctl restart oddo.service

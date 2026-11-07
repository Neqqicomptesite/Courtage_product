#!/usr/bin/env bash
# Mise à jour automatique (timer systemd, toutes les 15 min, en root).
#
# Règles (revue externe, point 3) :
#  - seulement la branche « production » (poussée après les tests), jamais « main » ;
#  - seulement HORS des heures d'envoi (20 h – 7 h, heure du Maroc), pour ne jamais couper
#    un envoi en cours ; pour forcer une mise à jour urgente : touch /etc/oddo/update-now ;
#  - sauvegarde de la base AVANT d'appliquer (les migrations s'appliquent au redémarrage) ;
#  - le code appartient à root : l'appli (utilisateur oddo) ne peut pas le modifier ;
#  - les fichiers système (services, ce script, la sauvegarde) ne sont PAS réinstallés
#    automatiquement : seulement à la main, avec deploy/install.sh.
set -euo pipefail
APP=/opt/oddo
BRANCH=production
FORCE=/etc/oddo/update-now
HOUR=$(TZ=Africa/Casablanca date +%-H)
if [ ! -f "$FORCE" ] && [ "$HOUR" -ge 7 ] && [ "$HOUR" -lt 20 ]; then exit 0; fi

# code en lecture seule pour l'appli (une fois pour toutes, sans effet ensuite)
if [ "$(stat -c %U "$APP")" != "root" ]; then chown -R root:root "$APP"; fi
chmod 700 "$APP/.git"

git -C "$APP" fetch -q --depth 20 origin "+refs/heads/$BRANCH:refs/remotes/origin/$BRANCH"
if [ "$(git -C "$APP" rev-parse HEAD)" = "$(git -C "$APP" rev-parse "origin/$BRANCH")" ]; then
  rm -f "$FORCE"; exit 0
fi
echo "Mise à jour $(git -C "$APP" rev-parse --short HEAD) -> $(git -C "$APP" rev-parse --short "origin/$BRANCH")"
/usr/local/sbin/backup.sh || { echo "Sauvegarde en échec : mise à jour annulée"; exit 1; }
git -C "$APP" reset -q --hard "origin/$BRANCH"
"$APP/.venv/bin/pip" install -q -r "$APP/requirements.txt"
rm -f "$FORCE"
systemctl restart oddo.service
